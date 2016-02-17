"""
Classes for Projects within the Division.

Projects can be of different types, inheriting shared attributes and methods
from an abstract base class, while defining relevant project documentation
per class.

Projects are spatially defined through Areas of different types:
Administrative Regions (DPaW Regions and Districts, NRM/IBRA/IMCRA Regions),
Area of field work as the combined extent of sampling transects (if field work
occurs), Areas of relevance (Project findings apply to).
"""

from __future__ import (division, print_function, unicode_literals,
                        absolute_import)

from datetime import date
import json
import logging
import markdown

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import Permission
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import signals
from django.utils.encoding import python_2_unicode_compatible
from django.utils.html import strip_tags
from django.utils.translation import ugettext_lazy as _
from django.utils.safestring import mark_safe

from django_fsm.db.fields import FSMField, transition
from polymorphic import PolymorphicModel, PolymorphicManager

from pythia.documents.models import (
    ConceptPlan, ProjectPlan, ProgressReport, ProjectClosure, StudentReport)
from pythia.fields import Html2TextField, PythiaArrayField
from pythia.models import ActiveGeoModelManager, Audit, ActiveModel
from pythia.models import Program, WebResource, Division, Area, User
from pythia.reports.models import ARARReport



logger = logging.getLogger(__name__)


#Add additional attributes/methods to the model Meta class.
import django.db.models.options as options
options.DEFAULT_NAMES = options.DEFAULT_NAMES + ('display_order',)


def projects_upload_to(instance, filename):
    return "projects/{0}-{1}/{2}".format(instance.year, instance.number,
                                         filename)


NULL_CHOICES = ((None, _("Not applicable")), (False, _("Incomplete")),
                (True, _("Complete")))


class ProjectManager(PolymorphicManager, ActiveGeoModelManager):
    pass


def get_next_available_number_for_year(year):
    '''Return the lowest available project number for a given project year.'''
    numbers = list(Project.objects.filter(year=year).values("number"))
    if len(numbers) == 0:
        return 1
    else:
        return max([x['number'] for x in Project.objects.filter(
                year=year).values("number")]) + 1

@python_2_unicode_compatible
class ResearchFunction(PolymorphicModel, Audit, ActiveModel):
    """A project contributes to a research function.
    Reports will summarise project progress reports bt research function.
    """
    name = Html2TextField(
        verbose_name=_("Name"),
        help_text=_("The research function's name with formatting if required."))
    description = Html2TextField(
        verbose_name=_("Description"),
        null=True, blank=True,
        help_text=_("The research function's description with formatting if required."))
    association = Html2TextField(
        verbose_name=_("Association"),
        null=True, blank=True,
        help_text=_("The research function's association with departmental programs."))
    leader = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("Function Leader"),
        related_name='pythia_researchfunction_leader',
        null=True, blank=True,
        help_text=_("The scientist in charge of the Research Function."))

    objects = ProjectManager()


    def __str__(self):
        return mark_safe(strip_tags(self.name))

@python_2_unicode_compatible
class Project(PolymorphicModel, Audit, ActiveModel):
    """
    A Project is the core object in the system.
    A Project is an endeavour of a team of staff, where staff and financial
    resources are allocated to address a specific problen and achieve an
    outcome that reflects the priorities of divisional strategy.
    It should contain all the top (project) level attributes.

    A project has a start and end date, which is indicated by its own date fields.
    The life cycle stage of a project is indicated by its status field.
    The life cycle stage transitions are under control by its own can_<action>
    methods, which test whether a certain action is permitted considering
    the project's document approval statuses.
    """
    STATUS_NEW = 'new'
    STATUS_PENDING = 'pending'
    STATUS_ACTIVE = 'active'
    STATUS_UPDATE = 'updating'
    STATUS_CLOSURE_REQUESTED = 'closure requested'
    STATUS_CLOSING = 'closing'
    STATUS_FINAL_UPDATE = 'final update'
    STATUS_COMPLETED = 'completed'
    STATUS_TERMINATED = 'terminated'
    STATUS_SUSPENDED = 'suspended'

    ACTIVE = (STATUS_NEW, STATUS_PENDING, STATUS_ACTIVE, STATUS_UPDATE,
            STATUS_CLOSURE_REQUESTED, STATUS_CLOSING, STATUS_FINAL_UPDATE)

    STATUS_CHOICES = (
        (STATUS_NEW, _("New project, pending concept plan approval")),
        (STATUS_PENDING, _("Pending project plan approval")),
        (STATUS_ACTIVE, _("Approved and active")),
        (STATUS_UPDATE, _("Update requested")),
        (STATUS_CLOSURE_REQUESTED,
            _("Closure pending approval of closure form")),
        (STATUS_CLOSING, _("Closure pending final update")),
        (STATUS_FINAL_UPDATE, _("Final update requested")),
        (STATUS_COMPLETED, _("Completed and closed")),
        (STATUS_TERMINATED, _("Terminated and closed")),
        (STATUS_SUSPENDED, _("Suspended"))
    )

    SCIENCE_PROJECT = 0
    CORE_PROJECT = 1
    COLLABORATION_PROJECT = 2
    STUDENT_PROJECT = 3
    PROJECT_TYPES = (
        (SCIENCE_PROJECT, _('Science project')),
        (CORE_PROJECT, _('Core function project')),
        (COLLABORATION_PROJECT, _('Collaboration project')),
        (STUDENT_PROJECT, _('Student project')),
    )

    PROJECT_ABBREVIATIONS = {
        SCIENCE_PROJECT: 'SP',
        CORE_PROJECT: 'CF',
        COLLABORATION_PROJECT: 'EXT',
        STUDENT_PROJECT: 'STP'
    }

    type = models.PositiveSmallIntegerField(
        verbose_name=_("Project type"), choices=PROJECT_TYPES, default=0,
        help_text=_("The project type determines the approval and "
            "documentation requirements during the project's life span. "
            "Choose wisely - you will not be able to change the project "
            "type later."))

    status = FSMField(
        default=STATUS_NEW, choices=STATUS_CHOICES,
        verbose_name=_("Project Status"))
    year = models.PositiveIntegerField(
        verbose_name=_("Project year"),
        #editable=False,
        default=lambda: date.today().year,
        help_text=_("The project year with four digits, e.g. 2014"))
    number = models.PositiveIntegerField(
        verbose_name=_("Project number"),
        default=lambda: get_next_available_number_for_year(date.today().year),
        help_text=_("The running project number within the project year."))
    position = models.IntegerField(
        blank=True, null=True, default=1000,
        help_text=_("The primary ordering instance. If left to default, "
                    "ordering happends by project year and number (newest "
                    "first)."))

    #-------------------------------------------------------------------------#
    # Name, image, slogan
    #
    title = Html2TextField(
        verbose_name=_("Project title"),
        help_text=_("The project title with formatting if required."))
    image = models.ImageField(
        upload_to=projects_upload_to, blank=True, null=True,
        help_text="Upload an image which represents the meaning, or shows"
                  " a nice detail, or the team of the project.")
    tagline = Html2TextField(
        blank=True, null=True,
        help_text="Sell the project in one sentence to a wide audience.")
    comments = Html2TextField(
        blank=True, null=True,
        help_text=_("Any additional comments on the project."))

    #-------------------------------------------------------------------------#
    # Time frame of project activity
    #
    start_date = models.DateField(
        null=True, blank=True,
        help_text=_("The project start date, update the initial estimate "
                    "later. Use format YYYY-MM-DD, e.g. 2014-12-31."))
    end_date = models.DateField(
        null=True, blank=True,
        help_text=_("The project end date, update the initial estimate "
                    "later. Use format YYYY-MM-DD, e.g. 2014-12-31."))

    #-------------------------------------------------------------------------#
    # Affiliation and linkages
    #
    program = models.ForeignKey(
        Program, verbose_name=_("Science and Conservation Division Program"),
        blank=True, null=True,
        help_text=_("The Science and Conservation Division Program hosting "
                    "this project."))
    output_program = models.ForeignKey(
        Division, blank=True, null=True,
        verbose_name="Parks and Wildlife Service",
        help_text=_("The DPaW service that this project delivers outputs to."))
    research_function = models.ForeignKey(
        ResearchFunction, blank=True, null=True,
        verbose_name="Research Function",
        help_text=_("The SCD Research Function this project mainly contributes to."))
    areas = models.ManyToManyField(
        Area, blank=True,
        help_text="Areas of relevance")
    web_resources = models.ManyToManyField(
        WebResource, blank=True,
        help_text="Web resources of relevance: Data, Metadata, Wiki etc.")

    #-------------------------------------------------------------------------#
    # Important project roles
    #
    project_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("supervising scientist"),
        # clashes with sdis2
        related_name='pythia_project_owner',
        help_text=_("The supervising scientist."))
    data_custodian = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("data custodian"),
        # clashes with sdis2
        related_name='pythia_project_data_custodian', blank=True, null=True,
        help_text=_("The data custodian (SPP E25) responsible for data "
                    "management, publishing and metadata documentation"
                    " on the <a target=\"_\" href=\"http://internal-data.dpaw.wa.gov.au/\">data catalogue</a>."))
    site_custodian = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("site custodian"),
        # clashes with sdis2
        related_name='pythia_project_site_custodian', blank=True, null=True,
        help_text=_("The site custodian responsible for georeferencing and "
                    "publishing study sites and putting them through "
                    "corporate approval to mitigate conflicts of study sites "
                    "and corporate activities."))
    members = models.ManyToManyField(
        User, through='projects.ProjectMembership')

    #-------------------------------------------------------------------------#
    # Dirty Hacks: lookups are read often, but change seldomly
    #
    team_list_plain = models.TextField(
            verbose_name="Team list",
            editable=False,
            null=True, blank=True,
            help_text=_("Team member names in order of membership rank."))
    supervising_scientist_list_plain = models.TextField(
            verbose_name="Supervising Scientists list",
            editable=False,
            null=True, blank=True,
            help_text=_("Supervising Scientist names in order of membership"
                " rank. NOT the project owner, but all supervising scientists"
                " on the team."))
    area_list_dpaw_region = models.TextField(
            verbose_name="DPaW Region List",
            editable=False, null=True, blank=True,
            help_text=_("DPaW Region names."))
    area_list_dpaw_district = models.TextField(
            verbose_name="DPaW Region List",
            editable=False, null=True, blank=True,
            help_text=_("DPaW Region names."))
    area_list_ibra_imcra_region = models.TextField(
            verbose_name="DPaW Region List",
            editable=False, null=True, blank=True,
            help_text=_("DPaW Region names."))
    area_list_nrm_region = models.TextField(
            verbose_name="DPaW Region List",
            editable=False, null=True, blank=True,
            help_text=_("DPaW Region names."))
    # end dirty hacks
    #-------------------------------------------------------------------------#

    objects = ProjectManager()

    class Meta:
        verbose_name = _("Project")
        verbose_name_plural = _("Projects")
        unique_together = (("year", "number"))
        ordering = ['position', '-year', '-number']

    def __str__(self):
        return mark_safe("%s %s-%s %s" % (
            self.get_type_display(), self.year, self.number, strip_tags(self.title)))

    @property
    def fullname(self):
        return self.__str__()


    def save(self, *args, **kwargs):
        """
        Save the project and call its setup method.

        The setup method is the transition into the state PROJECT_NEW.

        The project owner is a project member by default (refs SDIS-241):
        If created, add a ProjectMembership for the project owner.
        """
        created = True if not self.pk else False

        if not self.number:
            self.number = self.get_next_available_number()
        super(Project, self).save(*args, **kwargs)

        if created:
            ProjectMembership.objects.create(
                project=self, user=self.project_owner,
                role=ProjectMembership.ROLE_SUPERVISING_SCIENTIST
            )
            self.setup()

    # Make self._meta accessible to templates
    @property
    def opts(self):
        """Returns `._meta` as property."""
        return self._meta

    #-------------------------------------------------------------------------#
    # Project numbers
    @classmethod
    def get_next_available_number_for_year(year):
        '''Return the lowest available project number for a given year.'''
        numbers = list(Project.objects.filter(year=year).values("number"))
        if len(numbers) == 0:
            return 1
        else:
            return max([x['number'] for x in Project.objects.filter(
                year=year).values("number")]) + 1

    def get_next_available_number(self):
        '''Return the lowest available project number in the project's year.'''
        return Project.get_next_available_number_for_year(self.year)


    '''TODO: order field orders projects depending on type
    distribute to individual project classes?'''
    #@property
    #def order_field(self):
    #    if self.project_type == 'COL':
    #        cd = self.get_doc('collaborationdetails')
    #        return cd.name
    #    if self.project_type == 'STP':
    #        return ('{0}, {1}'.format(self.project_owner.last_name,
    #        self.project_owner.first_name))
    #    else:
    #        return self.title

    #--------------------------------------------------------------------------#
    # Project approval
    #
    def setup(self):
        """
        Perform post-save project setup.
        """
        pass

    # NEW -> PENDING ----------------------------------------------------------#
    def can_endorse(self):
        """
        Gate-check prior to `endorse()`.

        A science project or core function can only become PENDING if its
        Concept Plan has been approved.
        Other projects are fast-tracked to status PROJECT_ACTIVE on `setup()`.
        """
        try:
            has_approved_conceptplan = self.documents.instance_of(
                    ConceptPlan).latest().is_approved
            msg = "Approved ConceptPlan found: {0}".format(
                    has_approved_conceptplan)
            logger.info(msg); print(msg)
            return has_approved_conceptplan
        except:
            msg = "ConceptPlan not found but required for project.endorse()!"
            logger.info(msg); print(msg)
            return False

    @transition(field=status,
            source=STATUS_NEW,
            target=STATUS_PENDING,
            conditions=['can_endorse'],
            permission="approve",
            save=True,
            verbose_name=_("Endorse Project"))
    def endorse(self):
        """
        Transition to move project to PENDING.

        Generates ProjectPlan as required for SPP and CF, skipped by others.
        """
        msg = "Project.endorse() about to add a ProjectPlan"
        logger.info(msg)
        if not self.documents.instance_of(ProjectPlan):
            ProjectPlan.objects.create(
                    project=self,
                    creator=self.creator,
                    modifier=self.modifier)
        msg = self.__dict__
        logger.info(msg)

    # PENDING -> ACTIVE -------------------------------------------------------#
    def can_approve(self):
        """
        Gate-check prior to `approve()`.

        A project can only become ACTIVE if its Project Plan is approved.
        """
        try:
            return self.documents.instance_of(ProjectPlan).latest().is_approved
        except:
            logger.info('ProjectPlan not found! Cannot approve Project without'
                    ' approved ProjectPlan!')
            return False

    @transition(field=status,
            source=STATUS_PENDING,
            target=STATUS_ACTIVE,
            conditions=['can_approve'],
            save=True,
            verbose_name=_("Approve Project"),
            permission="approve")
    def approve(self):
        """
        Transition to move the project to ACTIVE.
        """
        return

    # ACTIVE -> UPDATING ------------------------------------------------------#
    def can_request_update(self):
        """
        Gate-check prior to `request_update()`.

        Currently no checks.
        """
        # Does an ARAR need to exist?
        return True

    @transition(field=status,
            source=STATUS_ACTIVE,
            target=STATUS_UPDATE,
            conditions=['can_request_update'],
            save=True,
            verbose_name=_("Request update"),
            permission="approve")
    def request_update(self, report=None):
        """
        Transition to move the project to STATUS_UPDATING.

        Creates ProgressReport as required for SPP, CF.
        Override for STP to generate StudentReport, ignore for COL.
        """
	if report is None:
	    report = ARARReport.objects.all().latest()
	self.make_progressreport(report)
        return

    # UPDATING --> ACTIVE -----------------------------------------------------#
    def can_complete_update(self):
        """
        Gate-check prior to `complete_update()`.

        Allow the update to be complete when the document has been approved.
        WARNING: will check against the latest progress report to be approved.
        Could return True if no current ProgressReport has been requested and
        previous ProgressReport is approved. Assumes that `request_update()`
        has been called, and new projects joining the party during an active
        ARAR reporting cycle will get their `request_update()` called.

        Needs override for STP to check for StudentReport to be approved.
        """
        try:
            return self.documents.instance_of(ProgressReport).latest().is_approved
        except:
            logger.info('ProgressReport not found! Cannot complete update without '
                    'approved Progress Report!')
            return False

    @transition(field=status,
            source=STATUS_UPDATE,
            target=STATUS_ACTIVE,
            #conditions=['can_complete_update'],
            save=True,
            verbose_name=_("Complete update"),
            permission="submit")
    def complete_update(self):
        """
        Move the project back to ACTIVE after finishing its update.
        """


    # ACTIVE -> CLOSURE_REQUESTED ---------------------------------------------#
    def can_request_closure(self):
        """
        Gate-check prior to `request_closure()`.

        Currently no checks.
        """

        return True

    @transition(field=status,
            source=STATUS_ACTIVE,
            target=STATUS_CLOSURE_REQUESTED,
            conditions=['can_request_closure'],
            save=True,
            verbose_name=_("Request closure"),
            permission="submit")
    def request_closure(self):
        """Transition to move project to CLOSURE_REQUESTED.

        Creates ProjectClosure as required for SPP and CF,
        requires override to fast-track STP and COL to STATUS_COMPLETED.
        """
        ProjectClosure.objects.create(project=self,
             creator=self.creator, modifier=self.modifier)


    # CLOSURE_REQUESTED -> CLOSING --------------------------------------------#
    def can_accept_closure(self):
        """
        Gate-check prior to `accept_closure()`.

        Allow the update to progress to closing if the closure form
        has been approved.

        TODO: insert gate checks: is the projectplan updated with latest data
        management info, is the closure form approved
        """
        return self.documents.instance_of(ProjectClosure).latest().is_approved

    @transition(field=status,
            source=STATUS_CLOSURE_REQUESTED,
            target=STATUS_CLOSING,
            conditions=['can_accept_closure'],
            save=True,
            verbose_name=_("Accept closure"),
            permission="approve")
    def accept_closure(self):
        """
        Transition to move the project to CLOSING.
        """


    # CLOSING -> FINAL_UPDATE ------------------------------------------------#
    def can_request_final_update(self):
        """
        Gate-check prior to `request_final_update()`.

        Return true if a final update can be requested before the project is
        closed. As long as project is in STATUS_CLOSING, the project is cleared
        to join in with the ARAR updates one last time.

        Therefore, currently no checks required.
        """
        return True

    @transition(field=status,
            source=[STATUS_CLOSING, STATUS_COMPLETED],
            target=STATUS_FINAL_UPDATE,
            conditions=['can_request_final_update'],
            save=True,
            verbose_name=_("Request final update"),
            permission="approve")
    def request_final_update(self):
        """
        Transition to move the project to STATUS_FINAL_UPDATE.
        """
        ProgressReport.objects.create(project=self, creator=self.creator,
                is_final_report=True,
                modifier=self.modifier, year= date.today().year)

    # FINAL_UPDATE -> COMPLETED -----------------------------------------------#
    def can_complete(self):
        """
        Gate-check prior to `complete()`.

        Projects can be completed if the final progress report and project
        closure are approved.
        """
        lpr = self.documents.instance_of(ProgressReport).latest()
        return (lpr.is_final_report and lpr.is_approved and
                self.documents.instance_of(ProjectClosure).latest().is_approved)

    @transition(field=status,
            source=STATUS_FINAL_UPDATE,
            target=STATUS_COMPLETED,
            #conditions=['can_complete'],
            save=True,
            verbose_name=_("Complete final update"),
            permission="approve")
    def complete(self):
        """
        Transition to move the project to its COMPLETED state.
        No more actions are required of this project.
        Only reactivate() should be possible now.
        """

    # COMPLETED -> ACTIVE -----------------------------------------------------#
    def can_reactivate(self):
        """
        Gate-check prior to `reqctivate()`.

        Return true if the project can be reactivated.

        Currently no checks.
        """
        return True

    @transition(field=status,
            source=STATUS_COMPLETED,
            target=STATUS_ACTIVE,
            conditions=['can_reactivate'],
            save=True,
            verbose_name=_("Reactivate project"),
            permission="approve")
    def reactivate(self):
        """
        Transition to move the project to its ACTIVE state.
        """


    # ACTIVE -> TERMINATED ----------------------------------------------------#
    def can_terminate(self):
        """
        Return true if the project can be reactivated.
        """
        return True

    @transition(field=status,
            source=STATUS_ACTIVE,
            target=STATUS_TERMINATED,
            conditions=['can_terminate'],
            save=True,
            verbose_name=_("Terminate project"),
            permission="approve")
    def terminate(self):
        """
        Move the project to its TERMINATED state.
        """


    # TERMINATED -> ACTIVE ----------------------------------------------------#
    def can_reactivate_terminated(self):
        """
        Return true if the project can be reactivated from being terminated.
        """
        return True

    @transition(field=status,
            source=STATUS_TERMINATED,
            target=STATUS_ACTIVE,
            conditions=['can_reactivate_terminated'],
            save=True,
            verbose_name=_("Reactivate terminated project"),
            permission="approve")
    def reactivate_terminated(self):
        """
        Move the project to its ACTIVE state.
        """


    # ACTIVE -> SUSPENDED -----------------------------------------------------#
    def can_suspend(self):
        """
        Return true if the project can be suspended.
        """
        return True

    @transition(field=status,
            source=STATUS_ACTIVE,
            target=STATUS_SUSPENDED,
            conditions=['can_suspend'],
            save=True,
            verbose_name=_("Suspend project"),
            permission="approve")
    def suspend(self):
        """
        Move the project to its SUSPENDED state.
        """


    # SUSPENDED -> ACTIVE -----------------------------------------------------#
    def can_reactivate_suspended(self):
        """
        Return true if the project can be reactivated from suspension.
        """
        return True

    @transition(field=status,
            source=STATUS_SUSPENDED,
            target=STATUS_ACTIVE,
            conditions=['can_reactivate_suspended'],
            save=True,
            verbose_name=_("Reactivate suspended project"),
            permission="approve")
    def reactivate_suspended(self):
        """
        Move the project to its ACTIVE state.
        """

    # EMAIL NOTIFICATIONS ----------------------------------------------------#
    def get_users_to_notify(self, transition):
        #result = set()
        #if transition in (STATUS_ACTIVE, STATUS_COMPLETED,
        #        STATUS_TERMINATED, STATUS_SUSPENDED):
        result = set(self.members.all()) # reduce some duplication

        return result

    #-------------------------------------------------------------------------#
    # Project labels and short codes
    #
    # Project code = "TYPE YEAR-NUMBER"
    @classmethod
    def clsm_project_type_year_number(cls, t, y, n):
        return '{0} {1}-{2}'.format(
            Project.PROJECT_ABBREVIATIONS[t], y, str(n).zfill(3))

    # Project name = "TYPE YEAR-NUMBER TITLE"
    @classmethod
    def clsm_project_type_year_number_name(cls, t, y, n, na):
        return mark_safe('{0} {1}-{2} {3}'.format(
            Project.PROJECT_ABBREVIATIONS[t], y, str(n).zfill(3), na))

    @classmethod
    def clsm_project_year_number(cls, y, n):
        return '{0}-{1}'.format(y, str(n).zfill(3))

    @property
    def project_type_year_number(self):
        return Project.clsm_project_type_year_number(
            self.type, self.year, str(self.number).zfill(3))

    @property
    def project_year_number(self):
        return Project.clsm_project_year_number(
            self.year, str(self.number).zfill(3))

    @property
    def project_name_html(self):
        """Return the project name as HTML.
        MARKDOWN or HTML: use commented out section instead if db stores markdown.
        """
        #return mark_safe(markdown.markdown('{0} {1}-{2} {3}'.format(
        #    self.PROJECT_ABBREVIATIONS[self.type], self.year, str(self.number).zfill(3),
        #    self.title), extensions=['pythia.md_ext.subscript', 'pythia.md_ext.superscript',
        #                             'nl2br'], safe_mode='escape'))
        return mark_safe('{0} {1}-{2} {3}'.format(self.PROJECT_ABBREVIATIONS[self.type],
            self.year, str(self.number).zfill(3), self.title))


    @property
    def project_title_html(self):
        return mark_safe(self.title)
            #markdown.markdown(self.title,
            #extensions=['pythia.md_ext.subscript',
            #'pythia.md_ext.superscript','nl2br'], safe_mode='escape'))

    @property
    def title_plain(self):
        """
        Returns a plain text version of the project title.
        """
        # TODO remove markdown from project title
        return unicode(strip_tags(self.title)).strip()

    def get_team_list_plain(self):
        """
        Returns a plain text version of the team list.
        """
        return ", ".join([m.user.abbreviated_name for m in
            self.projectmembership_set.select_related('user').all().order_by(
                "position","user__last_name","user__first_name" )])

    def get_supervising_scientist_list_plain(self):
        """Return a string of Supervising Scientist names."""
        return ', '.join([x.user.abbreviated_name for x in
            ProjectMembership.objects.filter(project=self).filter(
            role=ProjectMembership.ROLE_SUPERVISING_SCIENTIST)])


    @property
    def progressreport(self, year):
        """Stub to return the progress report for a given year."""
        return None

    #-------------------------------------------------------------------------#
    # Team members
    #
    @property
    def team_students(self):
        """Return a string of all team members in role Student"""
        return ', '.join([x.user.get_full_name() for x in
            ProjectMembership.objects.filter(project=self,
            role=ProjectMembership.ROLE_SUPERVISED_STUDENT)])

    @property
    def team_list(self):
        "Return a list of lists of project team memberships"
        return[[m.get_role_display(),
                m.user.fullname,
                m.time_allocation] for m in self.projectmembership_set.all()]

    #-------------------------------------------------------------------------#
    # Areas
    #
    @property
    def area_dpaw_district(self):
        """Return a string of all areas of type Dpaw District"""
        return ', '.join([area.name for area in self.areas.filter(
            area_type=Area.AREA_TYPE_DPAW_DISTRICT)])

    @property
    def area_dpaw_region(self):
        """Return a string of all areas of type Dpaw Region"""
        return ', '.join([area.name for area in self.areas.filter(
            area_type=Area.AREA_TYPE_DPAW_REGION)])

    @property
    def area_ibra_imcra_region(self):
        """Return a string of all areas of type IBRA or IMCRA Region"""
        return ', '.join([area.name for area in self.areas.filter(
            area_type__in=[Area.AREA_TYPE_IBRA_REGION,
                Area.AREA_TYPE_IMCRA_REGION])])

    @property
    def area_nrm_region(self):
        """Return a string of all areas of type NRM Region"""
        return ', '.join([area.name for area in self.areas.filter(
            area_type=Area.AREA_TYPE_NRM_REGION)])

def project_areas_changed(sender, **kwargs):
    """Updates cached Area names on Project"""
    p = kwargs['instance']
    p.area_list_dpaw_region = p.area_dpaw_region
    p.area_list_dpaw_district = p.area_dpaw_district
    p.area_list_ibra_imcra_region = p.area_ibra_imcra_region
    p.area_list_nrm_region = p.area_nrm_region
    p.save(update_fields=[
        'area_list_dpaw_region',
        'area_list_dpaw_district',
        'area_list_ibra_imcra_region',
        'area_list_nrm_region'])
signals.m2m_changed.connect(project_areas_changed, sender=Project.areas.through)

class ScienceProject(Project):
    """
    An instantiated model for the main research project type.
    A Science Project is proposed by a Concept Plan, defined by a Project Plan,
    reported on annually by a Progress Report, and closed by a closure form
    after the last Progress Report.
    """

    class Meta:
        verbose_name = _("Science Project")
        verbose_name_plural = _("Science Projects")

    def setup(self):
        """Setting up new Science Project creates a Conceptplan if not existing.
        """
        if not self.documents.instance_of(ConceptPlan):
            ConceptPlan.objects.create(
                    project=self, creator=self.creator, modifier=self.modifier)

    @property
    def progressreport(self):
        """Return the latest progress report.
        TODO returns the latest progress report, not using the year.
        """
        return self.documents.instance_of(ProgressReport).latest() or None

    def get_progressreport(self, year):
        """Return the ProgressReport for a given year"""
        if not ProgressReport.objects.filter(project=self, year=year).exists():
            a = ARARReport.objects.get(year=year)
            self.make_progressreport(a)
        return ProgressReport.objects.get(project=self, year=year)

    def make_progressreport(self, report):
        """Create (if neccessary) a ProgressReport for the given year.
        Populate fields from previous ProgressReport.
        Call this function for each participating project when creating an ARAR.

        :param year: the integer year of the ProgressReport delivery,
            e.g. 2014 for FY2013-14
        :param report: an instance of ARARReport
        """
        msg = "Creating ProgressReport for {0}".format(self.__str__())
        logger.info(msg); print(msg)
        p, created = ProgressReport.objects.get_or_create(
                year=report.year, project=self)
        p.report = report
        if (created and ProgressReport.objects.filter(
            project=self, year=report.year-1).exists()):
            p0 = ProgressReport.objects.get(project=self, year=report.year-1)
            p.context = p0.context
            p.aims = p0.aims
            p.progress = p0.progress
            p.implications = p0.implications
            p.future = p0.future
        p.save()
        msg = "{0} Added ProgressReport for year {1} in report {2}".format(
            p.project.project_type_year_number, p.year, p.report)
        logger.info(msg); print(msg)

class CoreFunctionProject(Project):
    """
    A departmental Core Function is an ongoing activity requires only
    ongoing Progress Reports. There is no formal approval or closure process.
    """

    class Meta:
        verbose_name = _("Core Function")
        verbose_name_plural = _("Core Functions")

    def setup(self):
        """
        A Core Function is now the same as a Science Project.
        """
        ConceptPlan.objects.create(project=self, creator=self.creator,
                                   modifier=self.modifier)

    @property
    def progressreport(self):
        """Return the latest progress report.
        TODO returns the latest progress report, not using the year.
        """
        return self.documents.instance_of(ProgressReport).latest() or None

    def get_progressreport(self, year):
        """Return the ProgressReport for a given year"""
        if not ProgressReport.objects.filter(project=self, year=year).exists():
            a = ARARReport.objects.get(year=year)
            self.make_progressreport(a)
        return ProgressReport.objects.get(project=self, year=year)

    def make_progressreport(self, report):
        """Create (if neccessary) a ProgressReport for the given year.
        Populate fields from previous ProgressReport.
        Call this function for each participating project when creating an ARAR.

        :param year: the integer year of the ProgressReport delivery,
            e.g. 2014 for FY2013-14
        :param report: an instance of ARARReport
        """
        logger.info("Creating ProgressReport for {0}".format(self.__str__()))
        p, created = ProgressReport.objects.get_or_create(
                year=report.year, project=self)
        p.report = report # dat report better exist yo
        if (created and ProgressReport.objects.filter(project=self, year=report.year-1).exists()):
            p0 = ProgressReport.objects.get(project=self, year=report.year-1)
            p.context = p0.context
            p.aims = p0.aims
            p.progress = p0.progress
            p.implications = p0.implications
            p.future = p0.future
            logger.debug("{0} Populated ProgressReport for year {1} in report {2} from previous ProgressReport".format(
            p.project.project_type_year_number, p.year, p.report))
        p.save()
        logger.debug("{0} Added ProgressReport for year {1} in report {2}".format(
            p.project.project_type_year_number, p.year, p.report))


class CollaborationProject(Project):
    """
    An external Collaboration with academia, industry or government
    requires only registration, but no Progress Reports.
    """
    name = Html2TextField(
        max_length=2000,
        verbose_name=_("Collaboration name (with formatting)"),
        help_text=_("The collaboration name with formatting if required."))
    budget = Html2TextField(
            #PythiaArrayField(
        verbose_name=_("Total Budget"),
        help_text=_("Specify the total financial and staff time budget."),
        #default = json.dumps([
        #    ['Period', 'Amount'],
        #    ['', ''],
        #    ['', ''],
        #    ['', ''],
        #    ['', ''],
        #], cls=DjangoJSONEncoder)
        )
    staff_list_plain = models.TextField(
            verbose_name="DPaW Involvement",
            editable=False,
            null=True, blank=True,
            help_text=_("Staff names in order of membership rank."
                " Update by adding DPaW staff as team members."))


    class Meta:
        verbose_name = _("External Partnership")
        verbose_name_plural = _("External Partnerships")

    def setup(self):
        """
        A collaboration project is automatically approved.
        """
        self.status = self.STATUS_ACTIVE
        self.save(update_fields=['status'])

    def get_staff_list_plain(self):
        """Return a string of DPaW staff."""
        return ', '.join([x.user.abbreviated_name for x in
            ProjectMembership.objects.filter(project=self).filter(
            role__in=[
                ProjectMembership.ROLE_SUPERVISING_SCIENTIST,
                ProjectMembership.ROLE_RESEARCH_SCIENTIST,
                ProjectMembership.ROLE_TECHNICAL_OFFICER
                ])
        ])




    # Forbid actions non applicable to this project type
    def can_endorse(self):
        return False
    def can_approve(self):
        return False
    def can_request_update(self):
        return False
    def can_request_final_update(self):
        return False
    def can_complete(self):
        return False # TODO
    def can_terminate(self):
        return False # TODO
    def can_suspend(self):
        return False # TODO

    def request_closure(self):
        self.status = Project.STATUS_COMPLETED
        self.save(update_fields=['status'])

class StudentProject(Project):
    """
    Student Projects are academic collaborations involving a student's
    work, can be started without divisional approval and only require
    annual Progress Reports.
    """
    LEVEL_PHD = 0
    LEVEL_MSC = 1
    LEVEL_HON = 2
    LEVEL_4TH = 3
    LEVEL_3RD = 4
    LEVEL_UND = 5

    LEVELS = (
        (LEVEL_PHD, "PhD"),
        (LEVEL_MSC, "MSc"),
        (LEVEL_HON, "BSc (Honours)"),
        (LEVEL_4TH, "Yr 4 intern"),
        (LEVEL_3RD, "3rd year"),
        (LEVEL_UND, "Undergraduate project"),

    )

    level = models.PositiveSmallIntegerField(
        null=True, blank=True, choices=LEVELS, default=LEVEL_PHD,
        help_text=_("The academic qualification achieved through this "
                    "project."))
    organisation = models.TextField(
        verbose_name=_("Academic Organisation"), blank=True, null=True,
        help_text=_("The full name of the academic organisation."))

    student_list_plain = models.TextField(
            verbose_name="Student list",
            editable=False,
            null=True, blank=True,
            help_text=_("Student names in order of membership rank."))
    academic_list_plain = models.TextField(
            verbose_name="Academic",
            editable=False,
            null=True, blank=True,
            help_text=_("Academic supervisors in order of membership rank."
                " Update by adding team members as academic supervisors."))
    academic_list_plain_no_affiliation = models.TextField(
            verbose_name="Academic without affiliation",
            editable=False,
            null=True, blank=True,
            help_text=_("Academic supervisors without their affiliation "
                "in order of membership rank."
                " Update by adding team members as academic supervisors."))
    class Meta:
        verbose_name = _("Student Project")
        verbose_name_plural = _("Student Projects")

    @property
    def sort_value(self):
        """Return a value by which all objects of this class can be sorted by"""
        return self.project_owner.last_name

    def get_student_list_plain(self):
        """Return a string of Student names."""
        return ', '.join([x.user.abbreviated_name for x in
            ProjectMembership.objects.filter(project=self).filter(
            role=ProjectMembership.ROLE_SUPERVISED_STUDENT)])

    def get_academic_list_plain(self):
        """Return a string of DPaW staff."""
        return ', '.join([x.user.abbreviated_name for x in
            ProjectMembership.objects.filter(project=self).filter(
            role=ProjectMembership.ROLE_ACADEMIC_SUPERVISOR)])

    def get_academic_list_plain_no_affiliation(self):
        """Return a string of DPaW staff without their affiliation."""
        return ', '.join([x.user.abbreviated_name_no_affiliation for x in
            ProjectMembership.objects.filter(project=self).filter(
            role=ProjectMembership.ROLE_ACADEMIC_SUPERVISOR)])

    @property
    def academic(self):
        """Return a string of the Academic Supervisor name(s).
        """
        return ', '.join([x.user.abbreviated_name for x in
            ProjectMembership.objects.filter(project=self).filter(
            role=ProjectMembership.ROLE_ACADEMIC_SUPERVISOR)])

    @property
    def academic_no_affiliation(self):
        """Return a string of the Academic Supervisor name(s) without
        their affiliations.
        """
        return ', '.join([x.user.abbreviated_name_no_affiliation for x in
            ProjectMembership.objects.filter(project=self).filter(
            role=ProjectMembership.ROLE_ACADEMIC_SUPERVISOR)])

    @property
    def organisation_plain(self):
        return mark_safe(strip_tags(self.organisation))

    def setup(self):
        """
        A student project doesn't need approval, and starts its lifecycle
        in the approved state.
        """
        self.status = Project.STATUS_ACTIVE
        self.save(update_fields=['status'])

    @transition(field='status', save=True,
                source=Project.STATUS_ACTIVE,
                target=Project.STATUS_UPDATE,
                conditions=['can_request_update'])
    def request_update(self, report=None):
        """
        A student project update generates a Student Report instead of a
        Progress Report.
        """
        if report is None:
            report = ARARReport.objects.all().latest()
        self.make_progressreport(report)
        return None

    def can_complete_update(self):
        """
        The update can be completed once the student report has been approved.
        """
        if self.documents.instance_of(StudentReport).count() > 0:
            return self.documents.instance_of(StudentReport).latest().is_approved
        else:
            return False

    @transition(field='status',
            source=Project.STATUS_ACTIVE,
            target=Project.STATUS_CLOSURE_REQUESTED,
            conditions=['can_request_closure'], save=True,
            verbose_name=_("Request closure"), permission="submit")
    def request_closure(self):
        self.status = Project.STATUS_COMPLETED
        self.save(update_fields=['status'])

    # Forbid actions non applicable to this project type
    def can_endorse(self):
        return False
    def can_approve(self):
        return False
    def can_request_final_update(self):
        return False
    def can_complete(self):
        return False
    def can_terminate(self):
        return False
    def can_suspend(self):
        return False

    @property
    def progressreport(self):
        """Return the latest progress report.
        TODO returns the latest progress report, not using the year.
        """
        return self.documents.instance_of(StudentReport).latest() or None

    def get_progressreport(self, year):
        """Return the StudentReport for a given year"""
        if not StudentReport.objects.filter(project=self, year=year).exists():
            a = ARARReport.objects.get(year=year)
            self.make_progressreport(year, a.id)
        return ProgressReport.objects.get(project=self, year=year)

    def make_progressreport(self, report):
        """Create (if neccessary) a StudentReport for the given year.
        Populate fields from previous StudentReport.
        Call this function for each participating project when creating an ARAR.

        :param year: the integer year of the StudentReport delivery,
            e.g. 2014 for FY2013-14
        :param report: an instance of ARARReport
        """
        logger.info("Creating ProgressReport for {0}".format(self.__str__()))
        p, created = StudentReport.objects.get_or_create(
                year=report.year, project=self)
        p.report = report
        if (created and StudentReport.objects.filter(
            project=self, year=report.year-1).exists()):
            p0 = StudentReport.objects.get(project=self, year=report.year-1)
            p.progress_report = p0.progress_report
        p.save()
        logger.debug("{0} Added StudentReport for year {1} in report {2}".format(
            p.project.project_type_year_number, p.year, p.report))


PROJECT_CLASS_MAP = {
    Project.SCIENCE_PROJECT: ScienceProject,
    Project.CORE_PROJECT: CoreFunctionProject,
    Project.COLLABORATION_PROJECT: CollaborationProject,
    Project.STUDENT_PROJECT: StudentProject
}


@python_2_unicode_compatible
class ProjectMembership(models.Model):
    ROLE_SUPERVISING_SCIENTIST = 1
    ROLE_RESEARCH_SCIENTIST = 2
    ROLE_TECHNICAL_OFFICER = 3
    ROLE_EXTERNAL_PEER = 4
    ROLE_CONSULTED_PEER = 5
    ROLE_ACADEMIC_SUPERVISOR = 6
    ROLE_SUPERVISED_STUDENT = 7
    ROLE_EXTERNAL_COLLABORATOR = 8
    ROLE_GROUP = 9

    ROLE_CHOICES = (
        (ROLE_SUPERVISING_SCIENTIST, "Supervising Scientist"),
        (ROLE_RESEARCH_SCIENTIST, "Research Scientist"),
        (ROLE_TECHNICAL_OFFICER, "Technical Officer"),
        (ROLE_EXTERNAL_COLLABORATOR, "External Collaborator"),
        (ROLE_ACADEMIC_SUPERVISOR, "Academic Supervisor"),
        (ROLE_SUPERVISED_STUDENT, "Supervised Student"),
        (ROLE_EXTERNAL_PEER, "External Peer"),
        (ROLE_CONSULTED_PEER, "Consulted Peer"),
        (ROLE_GROUP, "Involved Group")
    )

    project = models.ForeignKey(
        Project, help_text=_("The project for the team membership."))
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        help_text=_("The DPaW staff member to participate in the project "
                    "team."))
    role = models.PositiveSmallIntegerField(
        choices=ROLE_CHOICES,
        help_text=_("The role this team member fills within this project."))
    time_allocation = models.FloatField(
        blank=True, null=True, default=0,
        verbose_name=_("Time allocation (0 to 1 FTE)"),
        help_text=_("Indicative time allocation as a fraction of a Full Time "
                    "Equivalent (220 person-days). Values between 0 and 1."))
    position = models.IntegerField(
        blank=True, null=True, verbose_name=_("List position"), default=100,
        help_text=_("The lowest position number comes first in the team "
                    "members list. Ignore to keep alphabetical order, "
                    "increase to shift member towards the end of the list, "
                    "decrease to promote member to beginning of the list."))
    comments = models.TextField(
        blank=True, null=True,
        help_text=_("Any comments clarifying the project membership."))


    class Meta:
        ordering = ['position']
        verbose_name = _("Project Membership")
        verbose_name_plural = _("Project Memberships")

    def __str__(self):
        return mark_safe("{0} ({1} - {2} - {3} FTE) [List position {4}] {5}".format(
            self.user.__str__(),
            self.project.project_type_year_number,
            self.get_role_display(), self.time_allocation,
            self.position, self.comments))

    # TODO
    # save():
    # for each project document, for the user:
    # assign permission "submit" (make codename) to user for doc object

def refresh_project_cache(p):
    """Refreshes all cached area and team fields of a Project p.
    """
    p.area_list_dpaw_region = p.area_dpaw_region
    p.area_list_dpaw_district = p.area_dpaw_district
    p.area_list_ibra_imcra_region = p.area_ibra_imcra_region
    p.area_list_nrm_region = p.area_nrm_region
    p.team_list_plain = p.get_team_list_plain()
    # TODO update supervising_scientist_list_plain
    p.supervising_scientist_list_plain = p.get_supervising_scientist_list_plain()
    p.save(update_fields=[
            'area_list_dpaw_region',
            'area_list_dpaw_district',
            'area_list_ibra_imcra_region',
            'area_list_nrm_region',
            'team_list_plain',
            'supervising_scientist_list_plain'])
    if (p._meta.model_name=='studentproject'):
        p.student_list_plain = p.get_student_list_plain()
        p.academic_list_plain = p.get_academic_list_plain()
        p.academic_list_plain_no_affiliation = p.get_academic_list_plain_no_affiliation()
        p.save(update_fields=['student_list_plain','academic_list_plain',])
        #p.staff_list_plain = p.get_staff_list_plain()
        #p.save(update_fields=['staff_list_plain'])
    return True

def refresh_all_project_caches():
    tmp = [refresh_project_cache(p) for p in
            Project.objects.select_related("projectmembership_set","area_set")]
    return len(tmp)


def refresh_project_member_cache_fields(projectmembership_instance, remove=False):
    """Refresh the cached Project.team_list_plain, student and staff lists
    """
    p = projectmembership_instance.project
    p.team_list_plain = p.get_team_list_plain()
    p.save(update_fields=['team_list_plain'])

    # give user permission to change team?
    #if remove:
    #    print("remove user permission to change or delete team memberships")
    # TODO remove user's permissions on documents
    #else:
    #    print("grant user permission to change or delete team memberships")


    # some crazyness for StudentProjects and CollaborationProjects
    if projectmembership_instance.role==ProjectMembership.ROLE_SUPERVISING_SCIENTIST:
        p.supervising_scientist_list_plain = p.get_supervising_scientist_list_plain()
        p.save(update_fields=['supervising_scientist_list_plain'])
    if (projectmembership_instance.role==ProjectMembership.ROLE_SUPERVISED_STUDENT and
    p._meta.model_name=='studentproject'):
        p.student_list_plain = p.get_student_list_plain()
        p.save(update_fields=['student_list_plain'])
    if (projectmembership_instance.role==ProjectMembership.ROLE_ACADEMIC_SUPERVISOR and
    p._meta.model_name=='studentproject'):
        p.academic_list_plain = p.get_academic_list_plain()
        p.academic_list_plain_no_affiliation = p.get_academic_list_plain_no_affiliation()
        p.save(update_fields=['academic_list_plain', 'academic_list_plain_no_affiliation',])
    if (p._meta.model_name=='collaborationproject'):
        p.staff_list_plain = p.get_staff_list_plain()
        p.save(update_fields=['staff_list_plain'])

# Comment out post-syncdb and post-save hooks before loaddata to dev/test/uat
def projectmembership_post_save(sender, instance, created, **kwargs):
    refresh_project_member_cache_fields(instance)
    from pythia.documents.utils import update_document_permissions
    [update_document_permissions(d) for d in instance.project.documents.all()]
    #from guardian.shortcuts import assign_perm
    #assign_perm('pythia.submit_project', instance.user, instance.project)
signals.post_save.connect(projectmembership_post_save, sender=ProjectMembership)

def projectmembership_post_delete(sender, instance, using, **kwargs):
    refresh_project_member_cache_fields(instance, remove=True)
signals.post_delete.connect(projectmembership_post_delete, sender=ProjectMembership)
