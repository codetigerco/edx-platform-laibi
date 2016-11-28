"""
This file contains celery tasks for email marketing signal handler.
"""
import json
import logging
import time

from celery import task
from django.contrib.sites.models import Site
from django.core.cache import cache

from email_marketing.models import EmailMarketingConfiguration
from student.models import EnrollStatusChange

from sailthru.sailthru_client import SailthruClient
from sailthru.sailthru_error import SailthruClientError

log = logging.getLogger(__name__)


# pylint: disable=not-callable
@task(bind=True, default_retry_delay=3600, max_retries=24)
def update_user(self, sailthru_vars, email, site_domain=None, new_user=False, activation=False):
    """
    Adds/updates Sailthru profile information for a user.
     Args:
        sailthru_vars(dict): User profile information to pass as 'vars' to Sailthru
        email(str): User email address
        new_user(boolean): True if new registration
        activation(boolean): True if activation request
    Returns:
        None
    """
    email_config = EmailMarketingConfiguration.current()
    if not email_config.enabled:
        return

    sailthru_client = SailthruClient(email_config.sailthru_key, email_config.sailthru_secret)
    try:
        sailthru_response = sailthru_client.api_post("user",
                                                     _create_sailthru_user_parm(sailthru_vars, email,
                                                                                new_user, email_config,
                                                                                site_domain=site_domain))

    except SailthruClientError as exc:
        log.error("Exception attempting to add/update user %s in Sailthru - %s", email, unicode(exc))
        raise self.retry(exc=exc,
                         countdown=email_config.sailthru_retry_interval,
                         max_retries=email_config.sailthru_max_retries)

    if not sailthru_response.is_ok():
        error = sailthru_response.get_error()
        log.error("Error attempting to add/update user in Sailthru: %s", error.get_message())
        if _retryable_sailthru_error(error):
            raise self.retry(countdown=email_config.sailthru_retry_interval,
                             max_retries=email_config.sailthru_max_retries)
        return

    # if activating user, send welcome email
    if activation and email_config.sailthru_activation_template:
        try:
            sailthru_response = sailthru_client.api_post("send",
                                                         {"email": email,
                                                          "template": email_config.sailthru_activation_template})
        except SailthruClientError as exc:
            log.error("Exception attempting to send welcome email to user %s in Sailthru - %s", email, unicode(exc))
            raise self.retry(exc=exc,
                             countdown=email_config.sailthru_retry_interval,
                             max_retries=email_config.sailthru_max_retries)

        if not sailthru_response.is_ok():
            error = sailthru_response.get_error()
            log.error("Error attempting to send welcome email to user in Sailthru: %s", error.get_message())
            if _retryable_sailthru_error(error):
                raise self.retry(countdown=email_config.sailthru_retry_interval,
                                 max_retries=email_config.sailthru_max_retries)


# pylint: disable=not-callable
@task(bind=True, default_retry_delay=3600, max_retries=24)
def update_user_email(self, new_email, old_email):
    """
    Adds/updates Sailthru when a user email address is changed
     Args:
        username(str): A string representation of user identifier
        old_email(str): Original email address
    Returns:
        None
    """
    email_config = EmailMarketingConfiguration.current()
    if not email_config.enabled:
        return

    # ignore if email not changed
    if new_email == old_email:
        return

    sailthru_parms = {"id": old_email, "key": "email", "keysconflict": "merge", "keys": {"email": new_email}}

    try:
        sailthru_client = SailthruClient(email_config.sailthru_key, email_config.sailthru_secret)
        sailthru_response = sailthru_client.api_post("user", sailthru_parms)
    except SailthruClientError as exc:
        log.error("Exception attempting to update email for %s in Sailthru - %s", old_email, unicode(exc))
        raise self.retry(exc=exc,
                         countdown=email_config.sailthru_retry_interval,
                         max_retries=email_config.sailthru_max_retries)

    if not sailthru_response.is_ok():
        error = sailthru_response.get_error()
        log.error("Error attempting to update user email address in Sailthru: %s", error.get_message())
        if _retryable_sailthru_error(error):
            raise self.retry(countdown=email_config.sailthru_retry_interval,
                             max_retries=email_config.sailthru_max_retries)


# pylint: disable=not-callable
@task(bind=True, default_retry_delay=3600, max_retries=24)
def update_marketing_config_list(self, domain):
    """
    Update Sailthru user list in email marketing config.
    """
    email_config = EmailMarketingConfiguration.current()
    if not email_config.enabled:
        return

    user_lists = json.loads(email_config.sailthru_user_list)
    if user_lists.get(domain):
        return
    try:
        domain_name = domain.split('.')[0]
        user_list_name = domain_name + '_user_list'
        user_lists[domain] = user_list_name
        user_lists = json.dumps(user_lists)
        config = EmailMarketingConfiguration(
            enabled=email_config.enabled,
            sailthru_key=email_config.sailthru_key,
            sailthru_secret=email_config.sailthru_secret,
            sailthru_new_user_list=email_config.sailthru_new_user_list,
            sailthru_user_list=user_lists,
            sailthru_retry_interval=email_config.sailthru_retry_interval,
            sailthru_max_retries=email_config.sailthru_max_retries,
            sailthru_activation_template=email_config.sailthru_activation_template,
            sailthru_abandoned_cart_template=email_config.sailthru_abandoned_cart_template,
            sailthru_abandoned_cart_delay=email_config.sailthru_abandoned_cart_delay,
            sailthru_enroll_template=email_config.sailthru_enroll_template,
            sailthru_upgrade_template=email_config.sailthru_upgrade_template,
            sailthru_purchase_template=email_config.sailthru_purchase_template,
            sailthru_get_tags_from_sailthru=email_config.sailthru_get_tags_from_sailthru,
            sailthru_content_cache_age=email_config.sailthru_content_cache_age,
            sailthru_enroll_cost=email_config.sailthru_enroll_cost,
            sailthru_lms_url_override=email_config.sailthru_lms_url_override
        )
        config.save()
    except Exception as exc:  # pylint: disable=broad-except
        log.error("Error saving email configuration")
        raise self.retry(exc=exc,
                         countdown=email_config.sailthru_retry_interval,
                         max_retries=email_config.sailthru_max_retries)


# pylint: disable=not-callable
@task(bind=True, default_retry_delay=3600, max_retries=24)
def create_sailthru_user_list(self, user_lists):
    """Create sailthru user list if currently not exists"""
    email_config = EmailMarketingConfiguration.current()
    if not email_config.enabled:
        return

    sailthru_client = SailthruClient(email_config.sailthru_key, email_config.sailthru_secret)
    if not _create_user_lists(sailthru_client, user_lists):
        raise self.retry(countdown=email_config.sailthru_retry_interval,
                         max_retries=email_config.sailthru_max_retries)


def _create_sailthru_user_parm(sailthru_vars, email, new_user, email_config, site_domain=None):
    """
    Create sailthru user create/update parms
    """
    sailthru_user = {'id': email, 'key': 'email'}
    sailthru_user['vars'] = dict(sailthru_vars, last_changed_time=int(time.time()))

    # if new user add to list
    if new_user and email_config.sailthru_user_list:
        user_lists = json.loads(email_config.sailthru_user_list)
        default_site = Site.objects.get_current()
        if site_domain:
            user_list_name = user_lists.get(site_domain)
            if user_list_name:
                sailthru_user['lists'] = {user_list_name: 1}
            else:
                sailthru_user['lists'] = {user_lists.get(default_site.domain): 1}
        else:
            sailthru_user['lists'] = {user_lists.get(default_site.domain): 1}

    return sailthru_user


# pylint: disable=not-callable
@task(bind=True, default_retry_delay=3600, max_retries=24)
def update_course_enrollment(self, email, course_url, event, mode,
                             course_id=None, message_id=None):  # pylint: disable=unused-argument
    """
    Adds/updates Sailthru when a user enrolls/unenrolls/adds to cart/purchases/upgrades a course
     Args:
        email(str): The user's email address
        course_url(str): Course home page url
        event(str): event type
        mode(str): enroll mode (audit, verification, ...)
        unit_cost: cost if purchase event
        course_id(str): course run id
        currency(str): currency if purchase event - currently ignored since Sailthru only supports USD
    Returns:
        None


    The event can be one of the following:
        EnrollStatusChange.enroll
            A free enroll (mode=audit or honor)
        EnrollStatusChange.unenroll
            An unenroll
        EnrollStatusChange.upgrade_start
            A paid upgrade added to cart - ignored
        EnrollStatusChange.upgrade_complete
            A paid upgrade purchase complete - ignored
        EnrollStatusChange.paid_start
            A non-free course added to cart - ignored
        EnrollStatusChange.paid_complete
            A non-free course purchase complete - ignored
    """

    email_config = EmailMarketingConfiguration.current()
    if not email_config.enabled:
        return

    # Use event type to figure out processing required
    unenroll = False
    send_template = None
    cost_in_cents = 0

    if event == EnrollStatusChange.enroll:
        send_template = email_config.sailthru_enroll_template
        # set cost so that Sailthru recognizes the event
        cost_in_cents = email_config.sailthru_enroll_cost

    elif event == EnrollStatusChange.unenroll:
        # unenroll - need to update list of unenrolled courses for user in Sailthru
        unenroll = True

    else:
        # All purchase events should be handled by ecommerce, so ignore
        return

    sailthru_client = SailthruClient(email_config.sailthru_key, email_config.sailthru_secret)

    # update the "unenrolled" course array in the user record on Sailthru
    if not _update_unenrolled_list(sailthru_client, email, course_url, unenroll):
        raise self.retry(countdown=email_config.sailthru_retry_interval,
                         max_retries=email_config.sailthru_max_retries)

    # if there is a cost, call Sailthru purchase api to record
    if cost_in_cents:

        # get course information if configured and appropriate event
        course_data = {}
        if email_config.sailthru_get_tags_from_sailthru:
            course_data = _get_course_content(course_url, sailthru_client, email_config)

        # build item description
        item = _build_purchase_item(course_id, course_url, cost_in_cents, mode, course_data)

        # build purchase api options list
        options = {}

        # add appropriate send template
        if send_template:
            options['send_template'] = send_template

        if not _record_purchase(sailthru_client, email, item, message_id, options):
            raise self.retry(countdown=email_config.sailthru_retry_interval,
                             max_retries=email_config.sailthru_max_retries)


def _build_purchase_item(course_id_string, course_url, cost_in_cents, mode, course_data):
    """
    Build Sailthru purchase item object
    :return: item
    """

    # build item description
    item = {
        'id': "{}-{}".format(course_id_string, mode),
        'url': course_url,
        'price': cost_in_cents,
        'qty': 1,
    }

    # make up title if we don't already have it from Sailthru
    if 'title' in course_data:
        item['title'] = course_data['title']
    else:
        item['title'] = 'Course {} mode: {}'.format(course_id_string, mode)

    if 'tags' in course_data:
        item['tags'] = course_data['tags']

    # add vars to item
    item['vars'] = dict(course_data.get('vars', {}), mode=mode, course_run_id=course_id_string)

    return item


def _record_purchase(sailthru_client, email, item, message_id, options):
    """
    Record a purchase in Sailthru
    :param sailthru_client:
    :param email:
    :param item:
    :param incomplete:
    :param message_id:
    :param options:
    :return: False it retryable error
    """
    try:
        sailthru_response = sailthru_client.purchase(email, [item],
                                                     message_id=message_id,
                                                     options=options)

        if not sailthru_response.is_ok():
            error = sailthru_response.get_error()
            log.error("Error attempting to record purchase in Sailthru: %s", error.get_message())
            return not _retryable_sailthru_error(error)

    except SailthruClientError as exc:
        log.error("Exception attempting to record purchase for %s in Sailthru - %s", email, unicode(exc))
        return False

    return True


def _get_course_content(course_url, sailthru_client, email_config):
    """
    Get course information using the Sailthru content api.

    If there is an error, just return with an empty response.
    :param course_url:
    :param sailthru_client:
    :return: dict with course information
    """
    # check cache first
    response = cache.get(course_url)
    if not response:
        try:
            sailthru_response = sailthru_client.api_get("content", {"id": course_url})

            if not sailthru_response.is_ok():
                return {}

            response = sailthru_response.json
            cache.set(course_url, response, email_config.sailthru_content_cache_age)

        except SailthruClientError:
            response = {}

    return response


def _create_user_lists(sailthru_client, user_lists):
    """
    Create sailthru user list if currently not exists in sailthru.
    :param sailthru_client:
    :param user_lists:
    :return: False if retryable error, else True
    """
    try:
        sailthru_get_response = sailthru_client.api_get("list", {})
        if not sailthru_get_response.is_ok():
            error = sailthru_get_response.get_error()
            log.info("Error attempting to read list record from Sailthru: %s", error.get_message())
            return not _retryable_sailthru_error(error)

        for key, value in user_lists.items():
            list_exist = False
            for user_list in sailthru_get_response.json['lists']:
                if user_list.get('name') == value:
                    list_exist = True

            if not list_exist:
                list_params = {'list': value, 'primary': 0, 'public_name': value}
                try:
                    sailthru_response = sailthru_client.api_post("list", list_params)
                except SailthruClientError as exc:
                    log.error("Exception attempting to list record for key %s in Sailthru - %s", key, unicode(exc))
                    return False

                if not sailthru_response.is_ok():
                    error = sailthru_response.get_error()
                    log.error("Error attempting to create list in Sailthru: %s", error.get_message())
                    return not _retryable_sailthru_error(error)
        return True
    except SailthruClientError as exc:
        log.error("Exception attempting to list record in Sailthru - %s", unicode(exc))
        return False


def _update_unenrolled_list(sailthru_client, email, course_url, unenroll):
    """
    Maintain a list of courses the user has unenrolled from in the Sailthru user record
    :param sailthru_client:
    :param email:
    :param email_config:
    :param course_url:
    :param unenroll:
    :return: False if retryable error, else True
    """
    try:
        # get the user 'vars' values from sailthru
        sailthru_response = sailthru_client.api_get("user", {"id": email, "fields": {"vars": 1}})
        if not sailthru_response.is_ok():
            error = sailthru_response.get_error()
            log.info("Error attempting to read user record from Sailthru: %s", error.get_message())
            return not _retryable_sailthru_error(error)

        response_json = sailthru_response.json

        unenroll_list = []
        if response_json and "vars" in response_json and response_json["vars"] \
                and "unenrolled" in response_json["vars"]:
            unenroll_list = response_json["vars"]["unenrolled"]

        changed = False
        # if unenrolling, add course to unenroll list
        if unenroll:
            if course_url not in unenroll_list:
                unenroll_list.append(course_url)
                changed = True

        # if enrolling, remove course from unenroll list
        elif course_url in unenroll_list:
            unenroll_list.remove(course_url)
            changed = True

        if changed:
            # write user record back
            sailthru_response = sailthru_client.api_post(
                "user", {'id': email, 'key': 'email', "vars": {"unenrolled": unenroll_list}})

            if not sailthru_response.is_ok():
                error = sailthru_response.get_error()
                log.info("Error attempting to update user record in Sailthru: %s", error.get_message())
                return not _retryable_sailthru_error(error)

        # everything worked
        return True

    except SailthruClientError as exc:
        log.error("Exception attempting to update user record for %s in Sailthru - %s", email, unicode(exc))
        return False


def _retryable_sailthru_error(error):
    """ Return True if error should be retried.

    9: Retryable internal error
    43: Rate limiting response
    others: Not retryable

    See: https://getstarted.sailthru.com/new-for-developers-overview/api/api-response-errors/
    """
    code = error.get_error_code()
    return code == 9 or code == 43
