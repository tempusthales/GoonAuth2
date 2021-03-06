import json
import re

import falcon
import redis
import requests

import helpers
from local_settings import COOKIE_SESSIONID, COOKIE_SESSIONHASH, COOKIE_BBUSERID, COOKIE_BBPASSWORD

"""
Settings
"""

# The number of minutes hashes are good for before they're deleted
HASH_LIFESPAN_MINS = 5
# A URL to look up SA users by their username
SA_PROFILE_URL = 'http://forums.somethingawful.com/member.php?action=getinfo&username='
# Cookies we'll need to spoof before we can verify a user's profile
SA_COOKIES = {
    'sessionid': COOKIE_SESSIONID,
    'sessionhash': COOKIE_SESSIONHASH,
    'bbuserid': COOKIE_BBUSERID,
    'bbpassword': COOKIE_BBPASSWORD
}
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB_NUM = 1


"""
Begin Server
"""

# Connect to the Redis DB (and automatically decode values because they're all going to be strings)
redis_db = redis.StrictRedis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB_NUM,
    decode_responses=True)


class RequireJSON(object):
    """
    The API is only intended to handle application/json requests and responses
    """
    def process_request(self, req, resp):
        if not req.client_accepts_json:
            raise falcon.HTTPNotAcceptable(
                'This API only supports JSON-encoded responses'
            )

        if req.method in ['POST']:
            if 'application/json' not in req.content_type:
                raise falcon.HTTPUnsupportedMediaType(
                    'This API only supports JSON-encoded requests'
                )


class GenerateHashResource:
    """
    Generate a unique identifier that a goon can post to their profile to verify their identity
    """
    def on_post(self, req, resp):
        # Get the username
        body = helpers.get_json(req)
        username = helpers.get_username(body)

        user_hash = redis_db.get(username)
        if not user_hash:
            user_hash = helpers.get_hash()
            redis_db.setex(username, HASH_LIFESPAN_MINS * 60, user_hash)

        resp.status = falcon.HTTP_OK
        resp.body = json.dumps({'hash': user_hash})


class ValidateUserResource:
    """
    Check the goon's profile page for the presence of their hash
    """
    def on_post(self, req, resp):
        body = helpers.get_json(req)
        username = helpers.get_username(body)

        user_hash = redis_db.get(username)
        if not user_hash:
            raise falcon.HTTPBadRequest(
                'Hash Missing',
                'A hash does not exist for this username. Run /generate_hash/ first'
            )

        # The URL to the user's profile page
        profile_url = SA_PROFILE_URL + username

        # We can't view user profiles unless we're logged in, so we'll need to use a
        # requests session and set some cookies
        session = requests.Session()
        raw_profile = session.get(profile_url, cookies=SA_COOKIES)

        # Do a regex search to find the user's hash in their profile page
        result = re.search(user_hash, raw_profile.text)

        resp.status = falcon.HTTP_OK
        resp.body = json.dumps({'validated': result is not None})


app = falcon.API(middleware=[
    RequireJSON()
])
generate_hash = GenerateHashResource()
validate_user = ValidateUserResource()
app.add_route('/v1/generate_hash', generate_hash)
app.add_route('/v1/validate_user', validate_user)
