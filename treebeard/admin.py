"""Django admin support for treebeard"""

import sys

from django import VERSION as DJANGO_VERSION

if DJANGO_VERSION < (1, 4):
    from django.conf.urls.defaults import patterns, url
else:
    from django.conf.urls import patterns, url

from django.contrib import admin, messages
from django.contrib.admin.views.main import ChangeList
from django.http import HttpResponse, HttpResponseBadRequest
from django.utils.translation import ugettext_lazy as _
if sys.version_info >= (3, 0):
    from django.utils.encoding import force_str
else:
    from django.utils.encoding import force_unicode as force_str

from treebeard.templatetags.admin_tree import check_empty_dict
from treebeard.exceptions import (InvalidPosition, MissingNodeOrderBy,
                                  InvalidMoveToDescendant, PathOverflow)
from treebeard.forms import MoveNodeForm
from treebeard.al_tree import AL_Node


class TreeChangeList(ChangeList):
    def get_ordering(self, *args):
        """
        Overriding ChangeList.get_ordering if using the Django version <= 1.3
        default of '-id' but passing through the >= 1.4 default of '[]'.
        """
        ordering = super(TreeChangeList, self).get_ordering(*args)

        if not isinstance(ordering, list) and check_empty_dict(self.params):
            return None, 'asc'
        return ordering


class TreeAdmin(admin.ModelAdmin):
    """Django Admin class for treebeard"""
    change_list_template = 'admin/tree_change_list.html'
    form = MoveNodeForm

    def get_changelist(self, request, **kwargs):
        return TreeChangeList

    def queryset(self, request):
        if issubclass(self.model, AL_Node):
            # AL Trees return a list instead of a QuerySet for .get_tree()
            # So we're returning the regular .queryset cause we will use
            # the old admin
            return super(TreeAdmin, self).queryset(request)
        else:
            return self.model.get_tree()

    def changelist_view(self, request, extra_context=None):
        if issubclass(self.model, AL_Node):
            # For AL trees, use the old admin display
            self.change_list_template = 'admin/tree_list.html'
        return super(TreeAdmin, self).changelist_view(request, extra_context)

    def get_urls(self):
        """
        Adds a url to move nodes to this admin
        """
        urls = super(TreeAdmin, self).get_urls()
        new_urls = patterns(
            '',
            url('^move/$', self.admin_site.admin_view(self.move_node), ),
            url(r'^jsi18n/$',
                'django.views.i18n.javascript_catalog',
                {'packages': ('treebeard',)}),
        )
        return new_urls + urls

    def get_node(self, node_id):
        return self.model.objects.get(pk=node_id)

    def move_node(self, request):
        try:
            node_id = request.POST['node_id']
            target_id = request.POST['sibling_id']
            as_child = bool(int(request.POST.get('as_child', 0)))
        except (KeyError, ValueError):
            # Some parameters were missing return a BadRequest
            return HttpResponseBadRequest('Malformed POST params')

        node = self.get_node(node_id)
        target = self.get_node(target_id)
        is_sorted = node.node_order_by is not None

        pos = {
            (True, True): 'sorted-child',
            (True, False): 'last-child',
            (False, True): 'sorted-sibling',
            (False, False): 'left',
        }[as_child, is_sorted]

        try:
            node.move(target, pos=pos)
            # Call the save method on the (reloaded) node in order to trigger
            # possible signal handlers etc.
            node = self.get_node(node.pk)
            node.save()
        except (MissingNodeOrderBy, PathOverflow, InvalidMoveToDescendant,
                InvalidPosition):
            e = sys.exc_info()[1]
            # An error was raised while trying to move the node, then set an
            # error message and return 400, this will cause a reload on the
            # client to show the message
            # error message and return 400, this will cause a reload on
            # the client to show the message
            messages.error(request,
                           _('Exception raised while moving node: %s') % _(
                               force_str(e)))
            return HttpResponseBadRequest('Exception raised during move')

        if as_child:
            msg = _('Moved node "%(node)s" as child of "%(other)s"')
        else:
            msg = _('Moved node "%(node)s" as sibling of "%(other)s"')
        messages.info(request, msg % {'node': node, 'other': target})
        return HttpResponse('OK')
