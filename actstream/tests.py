from random import choice

from django.db import connection
from django.db.models import get_model
from django.test import TestCase
from django.conf import settings
from django.contrib.auth.models import User, AnonymousUser, Group
from django.contrib.contenttypes.models import ContentType
from django.contrib.sites.models import Site
from django.template.loader import Template, Context
from django.db.models.signals import m2m_changed, pre_delete, pre_save, post_delete, post_save

from actstream.models import Action, Follow, model_stream, user_stream,\
    setup_generic_relations, HiddenAction
from actstream.actions import follow, unfollow
from actstream.exceptions import ModelNotActionable
from actstream.signals import action
from actstream import settings as actstream_settings
from django.utils.translation import get_language, activate

class NoSignalTestCase(TestCase):
    def _receiver_in_lookup_keys(self, receiver, lookup_keys):
        """
        Evaluate if the receiver is in the provided lookup_keys; instantly terminates when found.
        """
        for key in lookup_keys:
        #           print '%s - %s - %s' % (key[0], receiver[0][1], key[1])
            if (receiver[0][0] == key[0] or key[0] is None) and receiver[0][1] == key[1]:
                return True
        return False

    def _find_allowed_receivers(self, receivers, lookup_keys):
        """
        Searches the receivers, keeping any that have a lookup_key in the lookup_keys list
        """
        kept_receivers = []
        for receiver in receivers:
            if self._receiver_in_lookup_keys(receiver, lookup_keys):
                kept_receivers.append(receiver)
        return kept_receivers

    def _create_lookup_keys(self, sender_receivers_tuple_list):
        """
        Creates a signal lookup keys from the provided array of tuples.
        """
        lookup_keys = []

        for keep in sender_receivers_tuple_list:
            receiver = keep[0]
            sender = keep[1]
            lookup_key = (_make_id(receiver) if receiver else receiver, _make_id(sender))
            lookup_keys.append(lookup_key)
        return lookup_keys

    def _remove_disallowed_receivers(self, receivers, lookup_keys):
        """
        Searches the receivers, discarding any that have a lookup_key in the lookup_keys list
        """
        kept_receivers = []
        for receiver in receivers:
            if not self._receiver_in_lookup_keys(receiver, lookup_keys):
                kept_receivers.append(receiver)
        return kept_receivers

    def setUp(self, sender_receivers_to_keep=None, sender_receivers_to_discard=None):
        """
        Turns off signals from other apps

        The `sender_receivers_to_keep` can be set to an array of tuples (reciever, sender,), preserving matching signals.
        The `sender_receivers_to_discard` can be set to an array of tuples (reciever, sender,), discarding matching signals.
            with both, you can set the `receiver` to None if you want to target all signals for a model
        """
        self.m2m_changed_receivers = m2m_changed.receivers
        self.pre_delete_receivers = pre_delete.receivers
        self.pre_save_receivers = pre_save.receivers
        self.post_delete_receivers = post_delete.receivers
        self.post_save_receivers = post_save.receivers

        new_m2m_changed_receivers = []
        new_pre_delete_receivers = []
        new_pre_save_receivers = []
        new_post_delete_receivers = []
        new_post_save_receivers = []

        if sender_receivers_to_keep:
            lookup_keys = self._create_lookup_keys(sender_receivers_to_keep)
            new_m2m_changed_receivers = self._find_allowed_receivers(self.m2m_changed_receivers, lookup_keys)
            new_pre_delete_receivers = self._find_allowed_receivers(self.pre_delete_receivers, lookup_keys)
            new_pre_save_receivers = self._find_allowed_receivers(self.pre_save_receivers, lookup_keys)
            new_post_delete_receivers = self._find_allowed_receivers(self.post_delete_receivers, lookup_keys)
            new_post_save_receivers = self._find_allowed_receivers(self.post_save_receivers, lookup_keys)

        if sender_receivers_to_discard:
            lookup_keys = self._create_lookup_keys(sender_receivers_to_discard)

            new_m2m_changed_receivers = self._remove_disallowed_receivers(new_m2m_changed_receivers or self.m2m_changed_receivers, lookup_keys)
            new_pre_delete_receivers = self._remove_disallowed_receivers(new_pre_delete_receivers or self.pre_delete_receivers, lookup_keys)
            new_pre_save_receivers = self._remove_disallowed_receivers(new_pre_save_receivers or self.pre_save_receivers, lookup_keys)
            new_post_delete_receivers = self._remove_disallowed_receivers(new_post_delete_receivers or self.post_delete_receivers, lookup_keys)
            new_post_save_receivers = self._remove_disallowed_receivers(new_post_save_receivers or self.post_save_receivers, lookup_keys)

        m2m_changed.receivers = new_m2m_changed_receivers
        pre_delete.receivers = new_pre_delete_receivers
        pre_save.receivers = new_pre_save_receivers
        post_delete.receivers = new_post_delete_receivers
        post_save.receivers = new_post_save_receivers
        super(NoSignalTestCase, self).setUp()

    def tearDown(self):
        """
        Restores the signals that were turned off.
        """
        super(NoSignalTestCase, self).tearDown()
        m2m_changed.receivers = self.m2m_changed_receivers
        pre_delete.receivers = self.pre_delete_receivers
        pre_save.receivers = self.pre_save_receivers
        post_delete.receivers = self.post_delete_receivers
        post_save.receivers = self.post_save_receivers


class ActivityBaseTestCase(NoSignalTestCase):
    actstream_models = ()

    def setUp(self):
        self.old_MODELS = actstream_settings.MODELS
        self.old_language = get_language()
        activate('en')
        actstream_settings.MODELS = {}
        for model in self.actstream_models:
            actstream_settings.MODELS[model.lower()] = \
                get_model(*model.split('.'))
        setup_generic_relations()
        super(ActivityBaseTestCase, self).setUp()

    def tearDown(self):
        activate(self.old_language)
        actstream_settings.MODELS = self.old_MODELS
        super(ActivityBaseTestCase, self).tearDown()


class ActivityTestCase(ActivityBaseTestCase):
    urls = 'actstream.urls'
    actstream_models = ('auth.User', 'auth.Group', 'sites.Site')

    def setUp(self):
        super(ActivityTestCase, self).setUp()
        self.group = Group.objects.create(name='CoolGroup')
        self.user1 = User.objects.get_or_create(username='admin')[0]
        self.user1.set_password('admin')
        self.user1.is_superuser = self.user1.is_staff = True
        self.user1.save()
        self.user2 = User.objects.get_or_create(username='Two')[0]

        # User1 joins group
        self.user1.groups.add(self.group)
        action.send(self.user1, verb='joined', target=self.group)

        # User1 follows User2
        follow(self.user1, self.user2)

        # User2 joins group
        self.user2.groups.add(self.group)
        action.send(self.user2, verb='joined', target=self.group)

        # User2 follows group
        follow(self.user2, self.group)

        # User1 comments on group
        # Use a site object here and predict the "__unicode__ method output"
        action.send(self.user1, verb='commented on', target=self.group)
        self.comment = Site.objects.create(
            domain="admin: Sweet Group!...")

        # Group responds to comment
        action.send(self.group, verb='responded to', target=self.comment)

    def test_aauser1(self):
        self.assertEqual(map(unicode, self.user1.actor_actions.all()), [
            u'admin commented on CoolGroup 0 minutes ago',
            u'admin started following Two 0 minutes ago',
            u'admin joined CoolGroup 0 minutes ago',
        ])

    def test_user2(self):
        self.assertEqual(map(unicode, Action.objects.actor(self.user2)), [
            u'Two started following CoolGroup 0 minutes ago',
            u'Two joined CoolGroup 0 minutes ago',
        ])

    def test_group(self):
        self.assertEqual(map(unicode, Action.objects.actor(self.group)),
            [u'CoolGroup responded to admin: Sweet Group!... 0 minutes ago'])

    def test_empty_follow_stream(self):
        unfollow(self.user1, self.user2)
        self.assert_(not user_stream(self.user1))

    def test_stream(self):
        self.assertEqual(map(unicode, Action.objects.user(self.user1)), [
            u'Two started following CoolGroup 0 minutes ago',
            u'Two joined CoolGroup 0 minutes ago',
        ])
        self.assertEqual(map(unicode, Action.objects.user(self.user2)),
            [u'CoolGroup responded to admin: Sweet Group!... 0 minutes ago'])

    def test_delete_action(self):
        self.assertEqual(map(unicode,Action.objects.user(self.user1)),[
                         u'Two started following CoolGroup 0 minutes ago',
                         u'Two joined CoolGroup 0 minutes ago',
        ])
        HiddenAction.objects.create(user=self.user1, action=Action.objects.user(self.user1)[0])
        self.assertEqual(map(unicode,Action.objects.user(self.user1)),[
            u'Two joined CoolGroup 0 minutes ago',
            ])

    def test_stream_stale_follows(self):
        """
        Action.objects.user() should ignore Follow objects with stale actor
        references.
        """
        self.user2.delete()
        self.assert_(not 'Two' in str(Action.objects.user(self.user1)))

    def test_rss(self):
        rss = self.client.get('/feed/').content
        self.assert_(rss.startswith('<?xml version="1.0" encoding="utf-8"?>\n'
            '<rss xmlns:atom="http://www.w3.org/2005/Atom" version="2.0">'))
        self.assert_(rss.find('Activity feed for your followed actors') > -1)

    def test_atom(self):
        atom = self.client.get('/feed/atom/').content
        self.assert_(atom.startswith('<?xml version="1.0" encoding="utf-8"?>\n'
            '<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="%s">' %
                                     settings.LANGUAGE_CODE))
        self.assert_(atom.find('Activity feed for your followed actors') > -1)

    def test_action_object(self):
        action.send(self.user1, verb='created comment',
            action_object=self.comment, target=self.group)
        created_action = Action.objects.get(verb='created comment')

        self.assertEqual(created_action.actor, self.user1)
        self.assertEqual(created_action.action_object, self.comment)
        self.assertEqual(created_action.target, self.group)
        self.assertEqual(unicode(created_action),
            u'admin created comment admin: Sweet Group!... on CoolGroup 0 '
                'minutes ago')

    def test_doesnt_generate_duplicate_follow_records(self):
        g = Group.objects.get_or_create(name='DupGroup')[0]
        s = User.objects.get_or_create(username='dupuser')[0]

        f1 = follow(s, g)
        self.assertTrue(f1 is not None, "Should have received a new follow "
            "record")
        self.assertTrue(isinstance(f1, Follow), "Returns a Follow object")

        self.assertEquals(1, Follow.objects.filter(user=s, object_id=g.pk,
            content_type=ContentType.objects.get_for_model(g)).count(),
            "Should only have 1 follow record here")

        f2 = follow(s, g)
        self.assertEquals(1, Follow.objects.filter(user=s, object_id=g.pk,
            content_type=ContentType.objects.get_for_model(g)).count(),
            "Should still only have 1 follow record here")
        self.assertTrue(f2 is not None, "Should have received a Follow object")
        self.assertTrue(isinstance(f2, Follow), "Returns a Follow object")
        self.assertEquals(f1, f2, "Should have received the same Follow "
            "object that I first submitted")

    def test_zzzz_no_orphaned_actions(self):
        actions = self.user1.actor_actions.count()
        self.user2.delete()
        self.assertEqual(actions, self.user1.actor_actions.count() + 1)

    def test_generic_relation_accessors(self):
        self.assertEqual(self.user2.actor_actions.count(), 2)
        self.assertEqual(self.user2.target_actions.count(), 1)
        self.assertEqual(self.user2.action_object_actions.count(), 0)

    def test_bad_actionable_model(self):
        self.assertRaises(ModelNotActionable, follow, self.user1,
                          ContentType.objects.get_for_model(self.user1))

    def test_hidden_action(self):
        action = self.user1.actor_actions.all()[0]
        action.public = False
        action.save()
        self.assert_(not action in self.user1.actor_actions.public())

    def test_tag_follow_url(self):
        src = '{% load activity_tags %}{% activity_follow_url user %}'
        output = Template(src).render(Context({'user': self.user1}))
        ct = ContentType.objects.get_for_model(User)
        self.assertEqual(output, '/follow/%s/%s/' % (ct.pk, self.user1.pk))

    def test_tag_follow_label(self):
        src = '{% load activity_tags %}'\
            '{% activity_follow_label other_user yup nope %}'

        # Anonymous.
        output = Template(src).render(Context({'other_user': self.user1}))
        self.assertEqual(output, 'nope')

        output = Template(src).render(Context({'user': AnonymousUser(),
            'other_user': self.user1}))
        self.assertEqual(output, 'nope')

        # Non follower (user2 does not follow user1).
        output = Template(src).render(Context({'user': self.user2,
            'other_user': self.user1}))
        self.assertEqual(output, 'nope')

        # Follower (user1 follows user2).
        output = Template(src).render(Context({'user': self.user1,
            'other_user': self.user2}))
        self.assertEqual(output, 'yup')

    def test_model_actions_with_kwargs(self):
        """
        Testing the model_actions method of the ActionManager
        by passing kwargs
        """
        self.assertEqual(map(unicode, model_stream(self.user1, verb='commented on')), [
                u'admin commented on CoolGroup 0 minutes ago',
                ])

    def test_user_stream_with_kwargs(self):
        """
        Testing the user method of the ActionManager by passing additional
        filters in kwargs
        """
        self.assertEqual(map(unicode, Action.objects.user(self.user1, verb='joined')), [
                u'Two joined CoolGroup 0 minutes ago',
                ])

    def test_is_following_filter(self):
        src = '{% load activity_tags %}{% if user|is_following:group %}yup{% endif %}'
        self.assertEqual(Template(src).render(Context({
            'user': self.user2, 'group': self.group
        })), u'yup')
        self.assertEqual(Template(src).render(Context({
            'user': self.user1, 'group': self.group
        })), u'')


class ZombieTest(ActivityBaseTestCase):
    actstream_models = ('auth.User',)
    human = 10
    zombie = 1

    def setUp(self):
        super(ZombieTest, self).setUp()
        settings.DEBUG = True

        player_generator = lambda n, count: [User.objects.create(
            username='%s%d' % (n, i)) for i in range(count)]

        self.humans = player_generator('human', self.human)
        self.zombies = player_generator('zombie', self.zombie)

        self.zombie_apocalypse()

    def tearDown(self):
        settings.DEBUG = False
        super(ZombieTest, self).tearDown()

    def zombie_apocalypse(self):
        humans = self.humans[:]
        zombies = self.zombies[:]
        while humans:
            for z in self.zombies:
                victim = choice(humans)
                humans.remove(victim)
                zombies.append(victim)
                action.send(z, verb='killed', target=victim)
                if not humans:
                    break

    def check_query_count(self, queryset):
        ci = len(connection.queries)

        result = list([map(unicode, (x.actor, x.target, x.action_object))
            for x in queryset])
        self.assertTrue(len(connection.queries) - ci <= 4,
            'Too many queries, got %d expected no more than 4' %
                len(connection.queries))
        return result

    def test_query_count(self):
        queryset = model_stream(User)
        result = self.check_query_count(queryset)
        self.assertEqual(len(result), 10)

    def test_query_count_sliced(self):
        queryset = model_stream(User)[:5]
        result = self.check_query_count(queryset)
        self.assertEqual(len(result), 5)


class GFKManagerTestCase(TestCase):

    def setUp(self):
        self.user_ct = ContentType.objects.get_for_model(User)
        self.group_ct = ContentType.objects.get_for_model(Group)
        self.group, _ = Group.objects.get_or_create(name='CoolGroup')
        self.user1, _ = User.objects.get_or_create(username='admin')
        self.user2, _ = User.objects.get_or_create(username='Two')
        self.user3, _ = User.objects.get_or_create(username='Three')
        self.user4, _ = User.objects.get_or_create(username='Four')
        Action.objects.get_or_create(
            actor_content_type=self.user_ct,
            actor_object_id=self.user1.id,
            verb='followed',
            target_content_type=self.user_ct,
            target_object_id=self.user2.id
        )
        Action.objects.get_or_create(
            actor_content_type=self.user_ct,
            actor_object_id=self.user1.id,
            verb='followed',
            target_content_type=self.user_ct,
            target_object_id=self.user3.id
        )
        Action.objects.get_or_create(
            actor_content_type=self.user_ct,
            actor_object_id=self.user1.id,
            verb='followed',
            target_content_type=self.user_ct,
            target_object_id=self.user4.id
        )
        Action.objects.get_or_create(
            actor_content_type=self.user_ct,
            actor_object_id=self.user1.id,
            verb='joined',
            target_content_type=self.group_ct,
            target_object_id=self.group.id
        )

    def test_fetch_generic_relations(self):
        # baseline without fetch_generic_relations
        _actions = Action.objects.filter(actor_content_type=self.user_ct,
            actor_object_id=self.user1.id)
        actions = lambda: _actions._clone()
        num_content_types = len(set(actions().values_list(
            'target_content_type_id', flat=True)))
        n = actions().count()

        # compare to fetching only 1 generic relation
        self.assertNumQueries(n + 1,
            lambda: [a.target for a in actions()])
        self.assertNumQueries(num_content_types + 2,
            lambda: [a.target for a in
                actions().fetch_generic_relations('target')])

        action_targets = [(a.id, a.target) for a in actions()]
        action_targets_fetch_generic = [(a.id, a.target) for a in
                actions().fetch_generic_relations('target')]
        self.assertEqual(action_targets, action_targets_fetch_generic)

        # compare to fetching all generic relations
        num_content_types = len(set(sum(actions().values_list(
            'actor_content_type_id', 'target_content_type_id'), ())))
        self.assertNumQueries(2 * n + 1,
            lambda: [(a.actor, a.target) for a in actions()])
        self.assertNumQueries(num_content_types + 2,
            lambda: [(a.actor, a.target) for a in
                actions().fetch_generic_relations()])

        action_actor_targets = [(a.id, a.actor, a.target) for a in actions()]
        action_actor_targets_fetch_generic_all = [
            (a.id, a.actor, a.target) for a in
                actions().fetch_generic_relations()]
        self.assertEqual(action_actor_targets,
            action_actor_targets_fetch_generic_all)

        # fetch only 1 generic relation, but access both gfks
        self.assertNumQueries(n + num_content_types + 2,
            lambda: [(a.actor, a.target) for a in
                actions().fetch_generic_relations('target')])
        action_actor_targets_fetch_generic_target = [
            (a.id, a.actor, a.target) for a in
                actions().fetch_generic_relations('target')]
        self.assertEqual(action_actor_targets,
            action_actor_targets_fetch_generic_target)
