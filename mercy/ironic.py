# Copyright 2014 Hewlett-Packard Development Company, L.P.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

# Primarily cribbed from nova/virt/ironic/client_wrapper.py

import time

import ironicclient as ironic
from oslo_log import log as logging


LOG = logging.getLogger(__name__)


class IronicClientWrapper(object):
    """Ironic client wrapper class that encapsulates retry logic."""

    def __init__(self, ironic_endpoint):
        """Initialise the IronicClientWrapper for use."""
        self._cached_client = None
        self.ironic_endpoint = ironic_endpoint

    def _invalidate_cached_client(self):
        """Tell the wrapper to invalidate the cached ironic-client."""
        self._cached_client = None

    def _get_client(self):
        # If we've already constructed a valid, authed client, just return
        # that.
        if self._cached_client is not None:
            return self._cached_client

        # TODO(jroll) figure out how to get an auth token
        auth_token = 'lol'
        kwargs = {'os_auth_token': auth_token,
                  'ironic_url': self.ironic_endpoint}

        try:
            cli = ironic.client.get_client('1', **kwargs)
            # Cache the client so we don't have to reconstruct and
            # reauthenticate it every time we need it.
            self._cached_client = cli

        except ironic.exc.Unauthorized:
            LOG.error('Unable to authenticate Ironic client.')
            raise exception.IronicAuthError()

        return cli

    def _multi_getattr(self, obj, attr):
        """Support nested attribute path for getattr().

        :param obj: Root object.
        :param attr: Path of final attribute to get. E.g., "a.b.c.d"

        :returns: The value of the final named attribute.
        :raises: AttributeError will be raised if the path is invalid.
        """
        for attribute in attr.split("."):
            obj = getattr(obj, attribute)
        return obj

    def call(self, method, num_attempts, *args, **kwargs):
        """Call an Ironic client method and retry on errors.

        :param method: Name of the client method to call as a string.
        :param num_attempts: Number of attempts to make.
        :param args: Client method arguments.
        :param kwargs: Client method keyword arguments.

        :raises: NovaException if all retries failed.
        """
        retry_excs = (ironic.exc.ServiceUnavailable,
                      ironic.exc.ConnectionRefused,
                      ironic.exc.Conflict)
        retry_interval = 2

        for attempt in range(1, num_attempts + 1):
            client = self._get_client()

            try:
                return self._multi_getattr(client, method)(*args, **kwargs)
            except ironic.exc.Unauthorized:
                # In this case, the authorization token of the cached
                # ironic-client probably expired. So invalidate the cached
                # client and the next try will start with a fresh one.
                self._invalidate_cached_client()
                LOG.debug("The Ironic client became unauthorized. "
                          "Will attempt to reauthorize and try again.")
            except retry_excs:
                pass

            # We want to perform this logic for all exception cases listed
            # above.
            msg = ("Error contacting Ironic server for "
                   "'%(method)s'. Attempt %(attempt)d of %(total)d" %
                   {'method': method,
                    'attempt': attempt,
                    'total': num_attempts})
            if attempt == num_attempts:
                LOG.error(msg)
                raise exception.IronicError(msg)
            LOG.warning(msg)
            time.sleep(retry_interval)
