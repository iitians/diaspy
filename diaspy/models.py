#!/usr/bin/env python3


"""This module is only imported in other diaspy modules and
MUST NOT import anything.
"""


import json
import re

from diaspy import errors

class Aspect():
    """This class represents an aspect.

    Class can be initialized by passing either an id and/or name as
    parameters.
    If both are missing, an exception will be raised.
    """
    def __init__(self, connection, id, name=None):
        self._connection = connection
        self.id, self.name = id, name
        self._cached = []

    def getUsers(self, fetch = True):
        """Returns list of GUIDs of users who are listed in this aspect.
        """
        if fetch:
            request = self._connection.get('contacts.json?a_id={}'.format(self.id))
            self._cached = request.json()
        return self._cached

    def removeAspect(self):
        """
        --> POST /aspects/{id} HTTP/1.1
        --> _method=delete&authenticity_token={token}

        <-- HTTP/1.1 302 Found

        TODO: status_codes

        Removes whole aspect.
        :returns: None
        """
        request = self._connection.tokenFrom('contacts').delete('aspects/{}'.format(self.id))

        if request.status_code != 302:
            raise errors.AspectError('wrong status code: {0}'.format(request.status_code))

    def addUser(self, user_id):
        """Add user to current aspect.

        :param user_id: user to add to aspect
        :type user_id: int
        :returns: JSON from request

        --> POST /aspect_memberships HTTP/1.1
        --> Accept: application/json, text/javascript, */*; q=0.01
        --> Content-Type: application/json; charset=UTF-8

        --> {"aspect_id":123,"person_id":123}

        <-- HTTP/1.1 200 OK
        """
        data = {
                'aspect_id': self.id,
                'person_id': user_id
                }
        headers = {'content-type': 'application/json',
                   'accept': 'application/json'
                   }

        request = self._connection.tokenFrom('contacts').post('aspect_memberships', data=json.dumps(data), headers=headers)

        if request.status_code == 400:
            raise errors.AspectError('duplicate record, user already exists in aspect: {0}'.format(request.status_code))
        elif request.status_code == 404:
            raise errors.AspectError('user not found from this pod: {0}'.format(request.status_code))
        elif request.status_code != 200:
            raise errors.AspectError('wrong status code: {0}'.format(request.status_code))

        response = None
        try:
            response = request.json()
        except json.decoder.JSONDecodeError:
            """ Should be OK now, but I'll leave this commentary here 
            at first to see if anything comes up """
            # FIXME For some (?) reason removing users from aspects works, but
            # adding them is a no-go and Diaspora* kicks us out with CSRF errors.
            # Weird.
            pass

        if response is None:
            raise errors.CSRFProtectionKickedIn()

        # Now you should fetchguid(fetch_stream=False) on User to update aspect membership_id's
        # Or update it locally with the response
        return response

    def removeUser(self, user):
        """Remove user from current aspect.

        :param user: user to remove from aspect
        :type user: diaspy.people.User object
        """
        membership_id = None
        to_remove = None
        for each in user.aspectMemberships():
            print(self.id, each)
            if each.get('aspect', {}).get('id') == self.id:
                membership_id = each.get('id')
                to_remove = each
                break # no need to continue

        if membership_id is None:
            raise errors.UserIsNotMemberOfAspect(user, self)

        request = self._connection.delete('aspect_memberships/{0}'.format(membership_id))

        if request.status_code == 404:
            raise errors.AspectError('cannot remove user from aspect, probably tried too fast after adding: {0}'.format(request.status_code))

        elif request.status_code != 200:
            raise errors.AspectError('cannot remove user from aspect: {0}'.format(request.status_code))

        if 'contact' in user.data: # User object
            if to_remove: user.data['contact']['aspect_memberships'].remove( to_remove ) # remove local aspect membership_id
        else: # User object from Contacts()
            if to_remove: user.data['aspect_memberships'].remove( to_remove ) # remove local aspect membership_id
        return request.json()


class Notification():
    """This class represents single notification.
    """
    _who_regexp = re.compile(r'/people/([0-9a-f]+)["\']{1} class=["\']{1}hovercardable')
    _when_regexp = re.compile(r'[0-9]{4,4}(-[0-9]{2,2}){2,2} [0-9]{2,2}(:[0-9]{2,2}){2,2} UTC')
    _aboutid_regexp = re.compile(r'/posts/[0-9a-f]+')
    _htmltag_regexp = re.compile('</?[a-z]+( *[a-z_-]+=["\'].*?["\'])* */?>')

    def __init__(self, connection, data):
        self._connection = connection
        self.type = data['type']
        self._data = data[self.type]
        self.id = self._data['id']
        self.unread = self._data['unread']

    def __getitem__(self, key):
        """Returns a key from notification data.
        """
        return self._data[key]

    def __str__(self):
        """Returns notification note.
        """
        string = re.sub(self._htmltag_regexp, '', self._data['note_html'])
        string = string.strip().split('\n')[0]
        while '  ' in string: string = string.replace('  ', ' ')
        return string

    def __repr__(self):
        """Returns notification note with more details.
        """
        return '{0}: {1}'.format(self.when(), str(self))

    def about(self):
        """Returns id of post about which the notification is informing OR:
        If the id is None it means that it's about user so .who() is called.
        """
        about = self._aboutid_regexp.search(self._data['note_html'])
        if about is None: about = self.who()
        else: about = int(about.group(0)[7:])
        return about

    def who(self):
        """Returns list of guids of the users who caused you to get the notification.
        """
        return [who for who in self._who_regexp.findall(self._data['note_html'])]

    def when(self):
        """Returns UTC time as found in note_html.
        """
        return self._data['created_at']

    def mark(self, unread=False):
        """Marks notification to read/unread.
        Marks notification to read if `unread` is False.
        Marks notification to unread if `unread` is True.

        :param unread: which state set for notification
        :type unread: bool
        """
        headers = {'x-csrf-token': repr(self._connection)}
        params = {'set_unread': json.dumps(unread)}
        self._connection.put('notifications/{0}'.format(self['id']), params=params, headers=headers)
        self._data['unread'] = unread


class Conversation():
    """This class represents a conversation.

    .. note::
        Remember that you need to have access to the conversation.
    """
    def __init__(self, connection, id, fetch=True):
        """
        :param conv_id: id of the post and not the guid!
        :type conv_id: str
        :param connection: connection object used to authenticate
        :type connection: connection.Connection
        """
        self._connection = connection
        self.id = id
        self._data = {}
        if fetch: self._fetch()

    def _fetch(self):
        """Fetches JSON data representing conversation.
        """
        request = self._connection.get('conversations/{}.json'.format(self.id))
        if request.status_code == 200:
            self._data = request.json()['conversation']
        else:
            raise errors.ConversationError('cannot download conversation data: {0}'.format(request.status_code))

    def answer(self, text):
        """Answer that conversation

        :param text: text to answer.
        :type text: str
        """
        data = {'message[text]': text,
                'utf8': '&#x2713;',
                'authenticity_token': repr(self._connection)}

        request = self._connection.post('conversations/{}/messages'.format(self.id),
                                        data=data,
                                        headers={'accept': 'application/json'})
        if request.status_code != 200:
            raise errors.ConversationError('{0}: Answer could not be posted.'
                                           .format(request.status_code))
        return request.json()

    def delete(self):
        """Delete this conversation.
        Has to be implemented.
        """
        data = {'authenticity_token': repr(self._connection)}

        request = self._connection.delete('conversations/{0}/visibility/'
                                          .format(self.id),
                                          data=data,
                                          headers={'accept': 'application/json'})

        if request.status_code != 404:
            raise errors.ConversationError('{0}: Conversation could not be deleted.'
                                           .format(request.status_code))

    def get_subject(self):
        """Returns the subject of this conversation
        """
        return self._data['subject']


class Comment():
    """Represents comment on post.

    Does not require Connection() object. Note that you should not manually
    create `Comment()` objects -- they are designed to be created automatically
    by `Post()` objects.
    """
    def __init__(self, data):
        self._data = data
        self.id = data['id']
        self.guid = data['guid']

    def __str__(self):
        """Returns comment's text.
        """
        return self._data['text']

    def __repr__(self):
        """Returns comments text and author.
        Format: AUTHOR (AUTHOR'S GUID): COMMENT
        """
        return '{0} ({1}): {2}'.format(self.author(), self.author('guid'), str(self))

    def when(self):
        """Returns time when the comment had been created.
        """
        return self._data['created_at']

    def author(self, key='name'):
        """Returns author of the comment.
        """
        return self._data['author'][key]

class Comments():
    def __init__(self, comments=None):
        self._comments = comments

    def __iter__(self):
        if self._comments:
            for comment in self._comments:
                yield comment

    def __len__(self):
        if self._comments:
            return len(self._comments)

    def __getitem__(self, index):
        if self._comments:
            return self._comments[index]

    def __bool__(self):
        if self._comments:
            return True
        return False

    def ids(self):
        return [c.id for c in self._comments]

    def add(self, comment):
        """ Expects comment object
        TODO self._comments is None sometimes, have to look into it."""
        if comment and self._comments:
            self._comments.append(comment)

    def set(self, comments):
        """Sets comments wich already have a Comment obj"""
        if comments:
            self._comments = comments

    def set_json(self, json_comments):
        """Sets comments for this post from post data."""
        if json_comments:
            self._comments = [Comment(c) for c in json_comments]

class Post():
    """This class represents a post.

    .. note::
        Remember that you need to have access to the post.
    """
    def __init__(self, connection, id=0, guid='', fetch=True, comments=True, post_data=None):
        """
        :param id: id of the post (GUID is recommended)
        :type id: int
        :param guid: GUID of the post
        :type guid: str
        :param connection: connection object used to authenticate
        :type connection: connection.Connection
        :param fetch: defines whether to fetch post's data or not
        :type fetch: bool
        :param comments: defines whether to fetch post's comments or not (if True also data will be fetched)
        :type comments: bool
        :param post_data: contains post data so no need to fetch the post if this is set, until you want to update post data
        :type: json
        """
        if not (guid or id): raise TypeError('neither guid nor id was provided')
        self._connection = connection
        self.id = id
        self.guid = guid
        self._data = {}
        self.comments = Comments()
        if post_data:
            self._data = post_data

        if fetch: self._fetchdata()
        if comments:
            if not self._data: self._fetchdata()
            self._fetchcomments()
        else:
            if not self._data: self._fetchdata()
            self.comments.set_json( self['interactions']['comments'] )

    def __repr__(self):
        """Returns string containing more information then str().
        """
        return '{0} ({1}): {2}'.format(self._data['author']['name'], self._data['author']['guid'], self._data['text'])

    def __str__(self):
        """Returns text of a post.
        """
        return self._data['text']

    def __getitem__(self, key):
        """FIXME This is deprecated, use diaspy.models.Post.data() instead to access
        data of Post objects.
        """
        return self._data[key]

    def __dict__(self):
        """Returns dictionary of posts data.
        FIXME This is deprecated, use diaspy.models.Post.data() instead.
        """
        return self._data

    def _fetchdata(self):
        """This function retrieves data of the post.

        :returns: guid of post whose data was fetched
        """
        if self.id: id = self.id
        if self.guid: id = self.guid
        request = self._connection.get('posts/{0}.json'.format(id))
        if request.status_code != 200:
            raise errors.PostError('{0}: could not fetch data for post: {1}'.format(request.status_code, id))
        elif request:
            self._data = request.json()
        return self['guid']

    def _fetchcomments(self):
        """Retreives comments for this post.
        Retrieving comments via GUID will result in 404 error.
        DIASPORA* does not supply comments through /posts/:guid/ endpoint.
        """
        id = self._data['id']
        if self['interactions']['comments_count']:
            request = self._connection.get('posts/{0}/comments.json'.format(id))
            if request.status_code != 200:
                raise errors.PostError('{0}: could not fetch comments for post: {1}'.format(request.status_code, id))
            else:
                self.comments.set([Comment(c) for c in request.json()])

    def update(self):
        """Updates post data.
        FIXME This is deprecated.
        """
        print('diaspy.models.Post.update() is deprecated. Use diaspy.models.Post.update() instead.')
        self._fetchdata()
        self._fetchcomments()

    def fetch(self, comments = False):
        """Fetches post data.
        Use this function instead of diaspy.models.Post.update().
        """
        self._fetchdata()
        if comments:
            self._fetchcomments()
        return self

    def data(self, data = None):
        if data is not None:
            self._data = data
        return self._data

    def like(self):
        """This function likes a post.
        It abstracts the 'Like' functionality.

        :returns: dict -- json formatted like object.
        """
        data = {'authenticity_token': repr(self._connection)}

        request = self._connection.post('posts/{0}/likes'.format(self.id),    
                                        data=data,
                                        headers={'accept': 'application/json'})

        if request.status_code != 201:
            raise errors.PostError('{0}: Post could not be liked.'
                                   .format(request.status_code))

        likes_json = request.json()
        if likes_json:
            self._data['interactions']['likes'] = [likes_json]
        return likes_json

    def reshare(self):
        """This function reshares a post
        """
        data = {'root_guid': self._data['guid'],
                'authenticity_token': repr(self._connection)}

        request = self._connection.post('reshares',
                                        data=data,
                                        headers={'accept': 'application/json'})
        if request.status_code != 201:
            raise Exception('{0}: Post could not be reshared'.format(request.status_code))
        return request.json()

    def comment(self, text):
        """This function comments on a post

        :param text: text to comment.
        :type text: str
        """
        data = {'text': text,
                'authenticity_token': repr(self._connection)}
        request = self._connection.post('posts/{0}/comments'.format(self.id),
                                        data=data,
                                        headers={'accept': 'application/json'})

        if request.status_code != 201:
            raise Exception('{0}: Comment could not be posted.'
                            .format(request.status_code))
        return Comment(request.json())

    def vote_poll(self, poll_answer_id):
        """This function votes on a post's poll

        :param poll_answer_id: id to poll vote.
        :type poll_answer_id: int
        """
        poll_id = self._data['poll']['poll_id']
        data = {'poll_answer_id': poll_answer_id,
                'poll_id': poll_id,
                'post_id': self.id,
                'authenticity_token': repr(self._connection)}
        request = self._connection.post('posts/{0}/poll_participations'.format(self.id),
                                        data=data,
                                        headers={'accept': 'application/json'})
        if request.status_code != 201:
            raise Exception('{0}: Vote on poll failed.'
                            .format(request.status_code))
        return request.json()

    def hide(self):
        """
        ->    PUT /share_visibilities/42 HTTP/1.1
              post_id=123
        <-    HTTP/1.1 200 OK
        """
        headers = {'x-csrf-token': repr(self._connection)}
        params = {'post_id': json.dumps(self.id)}
        request = self._connection.put('share_visibilities/42', params=params, headers=headers)
        if request.status_code != 200:
            raise Exception('{0}: Failed to hide post.'
                            .format(request.status_code))

    def mute(self):
        """
        ->    POST /blocks HTTP/1.1
            {"block":{"person_id":123}}
        <-    HTTP/1.1 204 No Content 
        """
        headers = {'content-type':'application/json', 'x-csrf-token': repr(self._connection)}
        data = json.dumps({ 'block': { 'person_id' : self._data['author']['id'] } })
        request = self._connection.post('blocks', data=data, headers=headers)
        if request.status_code != 204:
            raise Exception('{0}: Failed to block person'
                            .format(request.status_code))

    def subscribe(self):
        """
        ->    POST /posts/123/participation HTTP/1.1
        <-    HTTP/1.1 201 Created
        """
        headers = {'x-csrf-token': repr(self._connection)}
        data = {}
        request = self._connection.post('posts/{}/participation'
                            .format( self.id ), data=data, headers=headers)
        if request.status_code != 201:
            raise Exception('{0}: Failed to subscribe to post'
                            .format(request.status_code))

    def unsubscribe(self):
        """
        ->    POST /posts/123/participation HTTP/1.1
              _method=delete
        <-    HTTP/1.1 200 OK
        """
        headers = {'x-csrf-token': repr(self._connection)}
        data = { "_method": "delete" }
        request = self._connection.post('posts/{}/participation'
                            .format( self.id ), headers=headers, data=data)
        if request.status_code != 200:
            raise Exception('{0}: Failed to unsubscribe to post'
                            .format(request.status_code))

    def report(self):
        """
        TODO
        """
        pass

    def delete(self):
        """ This function deletes this post
        """
        data = {'authenticity_token': repr(self._connection)}
        request = self._connection.delete('posts/{0}'.format(self.id),
                                          data=data,
                                          headers={'accept': 'application/json'})
        if request.status_code != 204:
            raise errors.PostError('{0}: Post could not be deleted'.format(request.status_code))

    def delete_comment(self, comment_id):
        """This function removes a comment from a post

        :param comment_id: id of the comment to remove.
        :type comment_id: str
        """
        data = {'authenticity_token': repr(self._connection)}
        request = self._connection.delete('posts/{0}/comments/{1}'
                                          .format(self.id, comment_id),
                                          data=data,
                                          headers={'accept': 'application/json'})

        if request.status_code != 204:
            raise errors.PostError('{0}: Comment could not be deleted'
                                   .format(request.status_code))

    def delete_like(self):
        """This function removes a like from a post
        """
        data = {'authenticity_token': repr(self._connection)}
        url = 'posts/{0}/likes/{1}'.format(self.id, self._data['interactions']['likes'][0]['id'])
        request = self._connection.delete(url, data=data)
        if request.status_code != 204:
            raise errors.PostError('{0}: Like could not be removed.'
                                   .format(request.status_code))

    def author(self, key='name'):
        """Returns author of the post.
        :param key: all keys available in data['author']
        """
        return self._data['author'][key]
