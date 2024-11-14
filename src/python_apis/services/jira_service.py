"""
Module providing the ADOrganizationalUnitService class for interacting with Active Directory
organizational units.
"""

from logging import getLogger
from os import getenv
from typing import Any

from dateutil import parser

from dev_tools import timing_decorator
from python_apis.apis import JiraConnection, SQLConnection
from python_apis.models import base, JiraComponent, JiraIssue, JiraRequestType

class JiraService:
    """Service class for interacting with Active Directory organizational units.
    """

    def __init__(
        self, jira_connection: JiraConnection = None, sql_connection: SQLConnection = None):
        """Initialize the ADOrganizationalUnitService with an ADConnection and a db connection.

        Args:
            jira_connection (JiraConnection, optional): An existing JiraConnection instance.
                If None, a new one will be created.
            sql_connection (SQLConnection, optional): An existing SQLConnection instance.
                If None, a new one will be created.
        """
        self.logger = getLogger(__name__)

        if sql_connection is None:
            sql_connection = self._get_sql_connection()
        self.sql_connection = sql_connection

        if jira_connection is None:
            jira_connection = self._get_jira_connection()
        self.jira_connection = jira_connection

    def _get_sql_connection(self) -> SQLConnection:
        """Create and return a SQLConnection instance based on environment variables.

        Returns:
            SQLConnection: A new SQLConnection instance configured from environment variables.
        """
        return SQLConnection(
            server=getenv('JIRA_DB_SERVER', getenv('DEFAULT_DB_SERVER')),
            database=getenv('JIRA_DB_NAME', getenv('DEFAULT_DB_NAME')),
            driver=getenv('JIRA_SQL_DRIVER', getenv('DEFAULT_SQL_DRIVER')),
        )

    def create_table(self):
        """Create the ADOrganizationalUnit table in the database if it does not exist."""
        base.Base.metadata.create_all(
            self.sql_connection.engine,
            tables=[JiraComponent.__table__, JiraIssue.__table__, JiraRequestType.__table__],
            checkfirst=True,
        )

    @timing_decorator
    def _get_jira_connection(self) -> JiraConnection:
        """Create and return an JiraConnection instance.

        Returns:
            JiraConnection: A new JiraConnection instance based on environment variables.
        """
        jira_endpoint = getenv('JIRA_ENDPOINT')
        jira_api_token = getenv('JIRA_API_TOKEN')
        jira_user = getenv('JIRA_USER')

        jira_connection = JiraConnection(
            endpoint=jira_endpoint,
            token=jira_api_token,
            user=jira_user,
        )
        return jira_connection

    @timing_decorator
    def get_issies_from_db(self) -> list[JiraIssue]:
        jira_issues = self.sql_connection.session.query(JiraIssue).all()
        return jira_issues

    @timing_decorator
    def get_components_from_db(self) -> list[JiraComponent]:
        jira_components = self.sql_connection.session.query(JiraComponent).all()
        return jira_components

    def extract_description(self, description_field):
        """
        Extract text from the description field.

        The description is in Atlassian Document Format (ADF), so we need to extract the text.

        Parameters:
            description_field (dict): The 'description' field from the issue.

        Returns:
            str: The extracted text, or None if description_field is None.
        """
        if not description_field:
            return None

        # Recursive function to extract text
        def extract_text(adf_node):
            text = ''
            if 'content' in adf_node:
                for node in adf_node['content']:
                    text += extract_text(node)
                    if node.get('type') == 'paragraph':
                        text += '\n'  # Add newline for paragraph separation
            elif adf_node.get('type') == 'text':
                text += adf_node.get('text', '')
            return text

        return extract_text(description_field).strip()

    def parse_datetime(self, datetime_str):
        """
        Parse an ISO8601 datetime string into a datetime object.

        Parameters:
            datetime_str (str): The datetime string to parse.

        Returns:
            datetime.datetime: The parsed datetime object, or None if input is None.
        """
        if datetime_str:
            return parser.isoparse(datetime_str)
        else:
            return None

    def _raw_issue_to_object(self, issue_data: dict[str, dict]):
        fields: dict[str, dict] = issue_data.get('fields', {})

        issue = JiraIssue(
            id=int(issue_data.get('id')),
            key=issue_data.get('key'),
            summary=fields.get('summary'),
            description=self.extract_description(fields.get('description')),
            status=fields.get('status', {}).get('name'),
            priority=fields.get('priority', {}).get('name'),
            issueType=fields.get('issuetype', {}).get('name'),
            created=self.parse_datetime(fields.get('created')),
            updated=self.parse_datetime(fields.get('updated')),
            project_key=fields.get('project', {}).get('key'),
            project_name=fields.get('project', {}).get('name'),
            projectId=fields.get('project', {}).get('id'),
        )

        # Handle parent for sub-tasks
        parent: dict[str, str] = fields.get('parent', {})
        issue.parent_id = parent.get('id') if parent else None
        issue.parent_key = parent.get('key') if parent else None
        issue.parent_summary = parent.get('fields').get('summary') if parent else None

        # Handle resolution
        resolution: dict[str, str] = fields.get('resolution', {})
        if resolution:
            resolution = resolution.get('name')
        issue.resolution = resolution

        # Handle assignee
        assignee: dict[str, str] = fields.get('assignee', {})
        issue.assignee_displayName = assignee.get('displayName') if assignee else None
        issue.assignee_accountId = assignee.get('accountId') if assignee else None
        issue.assignee_active = assignee.get('active') if assignee else None

        # Handle reporter
        reporter: dict[str, dict] = fields.get('reporter', {})
        issue.reporter_displayName = reporter.get('displayName')
        issue.reporter_accountId = reporter.get('accountId')
        issue.reporter_active = reporter.get('active')
        issue.reporter_email_address = reporter.get('emailAddress')

        # Handle components
        components: list[dict] = fields.get('components', [])
        issue.components = ', '.join([component.get('name') for component in components])

        # Handle labels
        labels: list[str] = fields.get('labels', [])
        issue.labels = ', '.join(labels)

        # Handle fixVersions
        fix_versions: list[dict] = fields.get('fixVersions', [])
        issue.fixVersions = ', '.join([version.get('name') for version in fix_versions])

        # Handle attachments
        attachments: list[dict] = fields.get('attachment', [])
        issue.attachment_count = len(attachments)

        # Handle custom fields
        issue.customfield_10116 = fields.get('customfield_10116')
        issue.customfield_10117 = fields.get('customfield_10117')
        issue.customfield_10157 = fields.get('customfield_10157')

        issue.customfield_10113 = None
        if fields.get('customfield_10113'):
            issue.customfield_10113 = fields.get('customfield_10113').get('value')
        issue.customfield_10113 = None
        if fields.get('customfield_10114'):
            issue.customfield_10114 = fields.get('customfield_10114')[0].get('value')
        issue.customfield_10118 = fields.get('customfield_10118')
        issue.customfield_10120 = fields.get('customfield_10120')

        customfield_10010: dict[str, dict] = fields.get('customfield_10010')
        if customfield_10010:
            request_type = customfield_10010.get('requestType')
            issue.request_type_id = request_type.get('id')
            issue.request_type_name = request_type.get('name')
            issue.request_type_description = request_type.get('description')

            current_status = customfield_10010.get('currentStatus')
            issue.current_status_name = current_status.get('status')
            issue.current_status_category = current_status.get('statusCategory')
            issue.current_status_date = current_status.get('statusDate').get('iso8601')

        return issue

    @timing_decorator
    def get_issues_from_jira(self, start_at: int = 0) -> list[JiraIssue]:
        url_suffix = 'search'
        parameters = {
            "jql": "project=UT",
            "startAt": start_at,
            "maxResults": 100,
        }
        raw_issues: dict[str, dict] = self.jira_connection.get_objects(url_suffix, parameters)

        jira_issues = []
        for issue_data in raw_issues['issues']:
            issue = self._raw_issue_to_object(issue_data)

            jira_issues.append(issue)

        print(len(jira_issues))
        if len(jira_issues) == 100:
            jira_issues += self.get_issues_from_jira(start_at + 100)
        return jira_issues

    def get_request_types_from_jira(self) -> list[JiraRequestType]:
        servicedesk_endpoint = getenv('JIRA_SERVICEDESK_ENDPOINT')
        url_suffix = 'servicedeskapi/requesttype'
        parameters = {
            "start": 0,
            "limit": 100,
        }

        raw_request_types: dict[str, dict] = self.jira_connection.get_objects(
            url_suffix, parameters, servicedesk_endpoint)
        jira_request_types = []

        for request_type_data in raw_request_types.get('values', []):
            request_type_data: dict[str, dict]

            request_type = JiraRequestType(
                id=int(request_type_data.get('id')),
                name=request_type_data.get('name'),
                description=request_type_data.get('description'),
                help_text=request_type_data.get('helpText'),
                service_desk_id=request_type_data.get('serviceDeskId')
            )

            jira_request_types.append(request_type)

        return jira_request_types


    @timing_decorator
    def get_components_from_jira(self) -> list[JiraComponent]:
        raw_components = self.jira_connection.get_objects(JiraComponent.URL_SUFFIX)
        jira_components = []

        for comp_data in raw_components:
            component = JiraComponent(
                id=int(comp_data.get('id')),
                name=comp_data.get('name'),
                description=comp_data.get('description'),
                assigneeType=comp_data.get('assigneeType'),
                realAssigneeType=comp_data.get('realAssigneeType'),
                project=comp_data.get('project'),
                projectId=comp_data.get('projectId'),
            )

            # Handle 'lead' nested dictionary
            lead = comp_data.get('lead', {})
            component.lead_displayName = lead.get('displayName', None)
            component.lead_accountId = lead.get('accountId', None)
            component.lead_active = lead.get('active', None)

            # Handle 'assignee' nested dictionary (if present)
            assignee = comp_data.get('assignee', {})
            component.assignee_displayName = assignee.get('displayName', None)
            component.assignee_accountId = assignee.get('accountId', None)
            component.assignee_active = assignee.get('active', None)

            # Handle 'realAssignee' nested dictionary (if present)
            real_assignee = comp_data.get('realAssignee', {})
            component.realAssignee_displayName = real_assignee.get('displayName', None)
            component.realAssignee_accountId = real_assignee.get('accountId', None)
            component.realAssignee_active = real_assignee.get('active', None)

            jira_components.append(component)

        return jira_components

    @timing_decorator
    def update_components_db(self):
        jira_components = self.get_components_from_jira()
        try:
            self.sql_connection.session.query(JiraComponent).delete()
            self.sql_connection.session.commit()

            self.sql_connection.session.add_all(jira_components)
            self.sql_connection.session.commit()
            self.logger.info('JiraComponent table has been successfully updated')
        except Exception as e:
            self.sql_connection.session.rollback()
            self.logger.error('Rolling back changes on JiraComponent, error: %s', e)
            raise e

    @timing_decorator
    def update_issues_db(self):
        jira_issues: list[JiraIssue] = self.get_issues_from_jira()
        try:
            self.sql_connection.update(jira_issues)
            self.logger.info('JiraIssue table has been successfully updated')
        except Exception as e:
            self.sql_connection.session.rollback()
            self.logger.error('Rolling back changes on JiraIssue, error: %s', e)
            raise e

    @timing_decorator
    def update_request_types_db(self):
        jira_request_types: list[JiraRequestType] = self.get_request_types_from_jira()
        try:
            self.sql_connection.update(jira_request_types)
            self.logger.info('JiraRequestType table has been successfully updated')
        except Exception as e:
            self.sql_connection.session.rollback()
            self.logger.error('Rolling back changes on JiraRequestType, error: %s', e)
            raise e
