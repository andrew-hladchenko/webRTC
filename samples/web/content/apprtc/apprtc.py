#!/usr/bin/python2.4
#
# Copyright 2011 Google Inc. All Rights Reserved.

"""WebRTC Demo

This module demonstrates the WebRTC API by implementing a simple video chat app.
"""

import cgi
import logging
import os
import random
import re
import json
import jinja2
import threading
import urllib
import webapp2
from google.appengine.api import memcache
from google.appengine.api import urlfetch

jinja_environment = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)))

LOOPBACK_CLIENT_ID = 'LOOPBACK_CLIENT_ID'
TURN_BASE_URL = 'https://computeengineondemand.appspot.com'
WSS_HOST = 'apprtc-ws.webrtc.org'
WSS_PORT = '8089'
CEOD_KEY = '4080218913'

def generate_random(length):
  word = ''
  for _ in range(length):
    word += random.choice('0123456789')
  return word

def is_chrome_for_android(user_agent):
  return 'Android' in user_agent and 'Chrome' in user_agent

# HD is on by default for desktop Chrome, but not Android or Firefox (yet)
def get_hd_default(user_agent):
  if 'Android' in user_agent or not 'Chrome' in user_agent:
    return 'false'
  return 'true'

# iceServers will be filled in by the TURN HTTP request.
def make_pc_config(ice_transports):
  config = { 'iceServers': [] };
  if ice_transports:
    config['iceTransports'] = ice_transports
  return config

def add_media_track_constraint(track_constraints, constraint_string):
  tokens = constraint_string.split(':')
  mandatory = True
  if len(tokens) == 2:
    # If specified, e.g. mandatory:minHeight=720, set mandatory appropriately.
    mandatory = (tokens[0] == 'mandatory')
  else:
    # Otherwise, default to mandatory, except for goog constraints, which
    # won't work in other browsers.
    mandatory = not tokens[0].startswith('goog')

  tokens = tokens[-1].split('=')
  if len(tokens) == 2:
    if mandatory:
      track_constraints['mandatory'][tokens[0]] = tokens[1]
    else:
      track_constraints['optional'].append({tokens[0]: tokens[1]})
  else:
    logging.error('Ignoring malformed constraint: ' + constraint_string)

def make_media_track_constraints(constraints_string):
  if not constraints_string or constraints_string.lower() == 'true':
    track_constraints = True
  elif constraints_string.lower() == 'false':
    track_constraints = False
  else:
    track_constraints = {'mandatory': {}, 'optional': []}
    for constraint_string in constraints_string.split(','):
      add_media_track_constraint(track_constraints, constraint_string)

  return track_constraints

def make_media_stream_constraints(audio, video, firefox_fake_device):
  stream_constraints = (
      {'audio': make_media_track_constraints(audio),
       'video': make_media_track_constraints(video)})
  if firefox_fake_device:
    stream_constraints['fake'] = True
  logging.info('Applying media constraints: ' + str(stream_constraints))
  return stream_constraints

def maybe_add_constraint(constraints, param, constraint):
  if (param.lower() == 'true'):
    constraints['optional'].append({constraint: True})
  elif (param.lower() == 'false'):
    constraints['optional'].append({constraint: False})

  return constraints

def make_pc_constraints(dtls, dscp, ipv6):
  constraints = { 'optional': [] }
  # Force on the new BWE in Chrome 35 and later.
  # TODO(juberti): Remove once Chrome 36 is stable.
  constraints['optional'].append({'googImprovedWifiBwe': True})
  maybe_add_constraint(constraints, dtls, 'DtlsSrtpKeyAgreement')
  maybe_add_constraint(constraints, dscp, 'googDscp')
  maybe_add_constraint(constraints, ipv6, 'googIPv6')

  return constraints

def make_offer_constraints():
  constraints = { 'mandatory': {}, 'optional': [] }
  return constraints

def append_url_arguments(request, link):
  arguments = request.arguments()
  if len(arguments) == 0:
    return link
  link += ('?' + cgi.escape(arguments[0], True) + '=' +
           cgi.escape(request.get(arguments[0]), True))
  for argument in arguments[1:]:
    link += ('&' + cgi.escape(argument, True) + '=' +
             cgi.escape(request.get(argument), True))
  return link

def get_wss_parameters(request):
  ws_host = request.get('wsh')
  ws_port = request.get('wsp')
  ws_tls = request.get('wstls')

  if not ws_host:
    ws_host = WSS_HOST
  if not ws_port:
    ws_port = WSS_PORT

  if ws_tls and ws_tls == 'false':
    wss_url = 'ws://' + ws_host + ':' + ws_port + '/ws'
    wss_post_url = 'http://' + ws_host + ':' + ws_port
  else:
    wss_url = 'wss://' + ws_host + ':' + ws_port + '/ws'
    wss_post_url = 'https://' + ws_host + ':' + ws_port
  return (wss_url, wss_post_url)

# Returns appropriate room parameters based on query parameters in the request.
# TODO(tkchin): move query parameter parsing to JS code.
def get_room_parameters(request, room_id, client_id, is_initiator):
  error_messages = []
  # Get the base url without arguments.
  base_url = request.path_url
  user_agent = request.headers['User-Agent']

  # HTML or JSON.
  response_type = request.get('t')
  # Which ICE candidates to allow. This is useful for forcing a call to run
  # over TURN, by setting it=relay.
  ice_transports = request.get('it')
  # Which TURN transport= to allow (i.e., only TURN URLs with transport=<tt>
  # will be used). This is useful for forcing a session to use TURN/TCP, by
  # setting it=relay&tt=tcp.
  turn_transports = request.get('tt')
  # A HTTP server that will be used to find the right TURN servers to use, as
  # described in http://tools.ietf.org/html/draft-uberti-rtcweb-turn-rest-00.
  turn_base_url = request.get('ts', default_value = TURN_BASE_URL)

  # Use "audio" and "video" to set the media stream constraints. Defined here:
  # http://goo.gl/V7cZg
  #
  # "true" and "false" are recognized and interpreted as bools, for example:
  #   "?audio=true&video=false" (Start an audio-only call.)
  #   "?audio=false" (Start a video-only call.)
  # If unspecified, the stream constraint defaults to True.
  #
  # To specify media track constraints, pass in a comma-separated list of
  # key/value pairs, separated by a "=". Examples:
  #   "?audio=googEchoCancellation=false,googAutoGainControl=true"
  #   (Disable echo cancellation and enable gain control.)
  #
  #   "?video=minWidth=1280,minHeight=720,googNoiseReduction=true"
  #   (Set the minimum resolution to 1280x720 and enable noise reduction.)
  #
  # Keys starting with "goog" will be added to the "optional" key; all others
  # will be added to the "mandatory" key.
  # To override this default behavior, add a "mandatory" or "optional" prefix
  # to each key, e.g.
  #   "?video=optional:minWidth=1280,optional:minHeight=720,
  #           mandatory:googNoiseReduction=true"
  #   (Try to do 1280x720, but be willing to live with less; enable
  #    noise reduction or die trying.)
  #
  # The audio keys are defined here: talk/app/webrtc/localaudiosource.cc
  # The video keys are defined here: talk/app/webrtc/videosource.cc
  audio = request.get('audio')
  video = request.get('video')

  # Pass firefox_fake_device=1 to pass fake: true in the media constraints,
  # which will make Firefox use its built-in fake device.
  firefox_fake_device = request.get('firefox_fake_device')

  # The hd parameter is a shorthand to determine whether to open the
  # camera at 720p. If no value is provided, use a platform-specific default.
  # When defaulting to HD, use optional constraints, in case the camera
  # doesn't actually support HD modes.
  hd = request.get('hd').lower()
  if hd and video:
    message = 'The "hd" parameter has overridden video=' + video
    logging.error(message)
    error_messages.append(message)
  if hd == 'true':
    video = 'mandatory:minWidth=1280,mandatory:minHeight=720'
  elif not hd and not video and get_hd_default(user_agent) == 'true':
    video = 'optional:minWidth=1280,optional:minHeight=720'

  if request.get('minre') or request.get('maxre'):
    message = ('The "minre" and "maxre" parameters are no longer supported. '
              'Use "video" instead.')
    logging.error(message)
    error_messages.append(message)

  # Allow preferred audio and video codecs to be overridden.
  audio_send_codec = request.get('asc', default_value = '')
  audio_receive_codec = request.get('arc', default_value = '')
  video_send_codec = request.get('vsc', default_value = '')
  video_receive_codec = request.get('vrc', default_value = '')

  # Read url param controlling whether we send stereo.
  stereo = request.get('stereo', default_value = '')

  # Read url param controlling whether we send Opus FEC.
  opusfec = request.get('opusfec', default_value = '')

  # Read url param for Opus max sample rate.
  opusmaxpbr = request.get('opusmaxpbr', default_value = '')

  # Read url params audio send bitrate (asbr) & audio receive bitrate (arbr)
  asbr = request.get('asbr', default_value = '')
  arbr = request.get('arbr', default_value = '')

  # Read url params video send bitrate (vsbr) & video receive bitrate (vrbr)
  vsbr = request.get('vsbr', default_value = '')
  vrbr = request.get('vrbr', default_value = '')

  # Read url params for the initial video send bitrate (vsibr)
  vsibr = request.get('vsibr', default_value = '')

  # Options for controlling various networking features.
  dtls = request.get('dtls')
  dscp = request.get('dscp')
  ipv6 = request.get('ipv6')

  # Stereoscopic rendering.  Expects remote video to be a side-by-side view of
  # two cameras' captures, which will each be fed to one eye.
  ssr = request.get('ssr')
  # Avoid pulling down vr.js (>25KB, minified) if not needed.
  include_vr_js = ''
  if ssr == 'true':
    include_vr_js = ('<script src="/js/vr.js"></script>\n' +
                     '<script src="/js/stereoscopic.js"></script>')

  debug = request.get('debug')
  if debug == 'loopback':
    # Set dtls to false as DTLS does not work for loopback.
    dtls = 'false'
    include_loopback_js = '<script src="/js/loopback.js"></script>'
  else:
    include_loopback_js = ''

  # TODO(tkchin): We want to provide a TURN request url on the initial get,
  # but we don't provide client_id until a register. For now just generate
  # a random id, but we should make this better.
  username = client_id if client_id is not None else generate_random(9)
  if len(turn_base_url) > 0:
    turn_url = '%s/turn?username=%s&key=%s' % \
        (turn_base_url, username, CEOD_KEY)

  room_link = request.host_url + '/room/' + room_id
  room_link = append_url_arguments(request, room_link)
  pc_config = make_pc_config(ice_transports)
  pc_constraints = make_pc_constraints(dtls, dscp, ipv6)
  offer_constraints = make_offer_constraints()
  media_constraints = make_media_stream_constraints(audio, video,
                                                    firefox_fake_device)
  wss_url, wss_post_url = get_wss_parameters(request)
  params = {
    'error_messages': error_messages,
    'is_loopback' : json.dumps(debug == 'loopback'),
    'room_id': room_id,
    'room_link': room_link,
    'pc_config': json.dumps(pc_config),
    'pc_constraints': json.dumps(pc_constraints),
    'offer_constraints': json.dumps(offer_constraints),
    'media_constraints': json.dumps(media_constraints),
    'turn_url': turn_url,
    'turn_transports': turn_transports,
    'stereo': stereo,
    'opusfec': opusfec,
    'opusmaxpbr': opusmaxpbr,
    'arbr': arbr,
    'asbr': asbr,
    'vrbr': vrbr,
    'vsbr': vsbr,
    'vsibr': vsibr,
    'audio_send_codec': audio_send_codec,
    'audio_receive_codec': audio_receive_codec,
    'video_send_codec': video_send_codec,
    'video_receive_codec': video_receive_codec,
    'ssr': ssr,
    'include_loopback_js' : include_loopback_js,
    'include_vr_js': include_vr_js,
    'wss_url': wss_url,
    'wss_post_url': wss_post_url
  }
  if client_id is not None:
    params['client_id'] = client_id
  if is_initiator is not None:
    params['is_initiator'] = json.dumps(is_initiator)
  return params

# For now we have (room_id, client_id) pairs are 'unique' but client_ids are
# not. Uniqueness is not enforced however and bad things may happen if RNG
# generates non-unique numbers. We also have a special loopback client id.
# TODO(tkchin): Generate room/client IDs in a unique way while handling
# loopback scenario correctly.
class Client:
  messages = []
  is_initiator = False
  def __init__(self, is_initiator):
    self.is_initiator = is_initiator
  def add_message(self, msg):
    self.messages.append(msg)
  def clear_messages(self):
    self.messages = []
  def on_other_client_leave(self):
    self.is_initiator = True
    self.messages = []

class Room:
  clients = {}
  def add_client(self, client_id, client):
    self.clients[client_id] = client
  def remove_client(self, client_id):
    del self.clients[client_id]
  def get_occupancy(self):
    return len(self.clients)
  def has_client(self, client_id):
    return client_id in self.clients
  def get_client(self, client_id):
    return self.clients[client_id]
  def get_other_client(self, client_id):
    for key, client in self.clients.items():
      if key is not client_id:
        return client
    return None
  def __str__(self):
    return str(self.clients.keys())

def get_memcache_key_for_room(host, room_id):
  return '%s/%s' % (host, room_id)

def add_client_to_room(host, room_id, client_id, is_loopback):
  key = get_memcache_key_for_room(host, room_id)
  memcache_client = memcache.Client()
  success = False
  # Compare and set retry loop.
  while True:
    is_initiator = False
    messages = []
    is_full = False
    room_state = ''
    room = memcache_client.gets(key)
    if room is None:
      if not memcache_client.set(key, Room()):
        logging.warning('memcache.Client.set failed for key ' + key)
        break
      room = memcache_client.gets(key)

    occupancy = room.get_occupancy()
    if occupancy >= 2:
      is_full = True
      break

    if occupancy == 0:
      is_initiator = True
      room.add_client(client_id, Client(is_initiator))
      if is_loopback:
        room.add_client(LOOPBACK_CLIENT_ID, Client(False))
    else:
      is_initiator = False
      other_client = room.get_other_client(client_id)
      messages = other_client.messages
      room.add_client(client_id, Client(is_initiator))
      other_client.clear_messages()
    room_state = str(room)
    if memcache_client.cas(key, room):
      logging.info('Added client ' + client_id + ' in room ' + room_id)
      success = True
      break
  return {'success': success, 'is_initiator': is_initiator,
          'messages': messages, 'is_full': is_full, 'room_state': room_state}

def remove_client_from_room(host, room_id, client_id):
  key = get_memcache_key_for_room(host, room_id)
  memcache_client = memcache.Client()
  # Compare and set retry loop.
  while True:
    room = memcache_client.gets(key)
    if room is None:
      logging.warning('Unknown room: ' + room_id)
      return None
    if not room.has_client(client_id):
      logging.warning('Unknown client ' + client_id + ' for room ' + room_id)
      return None

    room.remove_client(client_id)
    if room.has_client(LOOPBACK_CLIENT_ID):
      room.remove_client(LOOPBACK_CLIENT_ID)
    if room.get_occupancy() > 0:
      room.get_other_client(client_id).on_other_client_leave()
    else:
      room = None

    if memcache_client.cas(key, room):
      logging.info('Removed client ' + client_id + ' from room ' + room_id)
      return str(room)

def save_message_from_client(host, room_id, client_id, message):
  key = get_memcache_key_for_room(host, room_id)
  memcache_client = memcache.Client()
  # Compare and set retry loop.
  while True:
    room = memcache_client.gets(key)
    if room is None:
      logging.warning('Unknown room: ' + room_id)
      return {'error': 'UNKNOWN_ROOM', 'saved': False}
    if not room.has_client(client_id):
      logging.warning('Unknown client: ' + client_id)
      return {'error': 'UNKNOWN_CLIENT', 'saved': False}
    if room.get_occupancy() > 1:
      return {'error': None, 'saved': False}

    try:
      text = message.encode(encoding='utf-8', errors='strict')
    except Exception as e:
      return {'error': 'ENCODE_ERROR', 'saved': False}
    room.get_client(client_id).add_message(text)
    if memcache_client.cas(key, room):
      return {'error': None, 'saved': True}

class ByePage(webapp2.RequestHandler):
  def post(self, room_id, client_id):
    room_state = remove_client_from_room(
        self.request.host_url, room_id, client_id)
    if room_state is not None:
      logging.info('Room ' + room_id + ' has state ' + room_state)

class MessagePage(webapp2.RequestHandler):
  def write_response(self, result):
    content = json.dumps({ 'result' : result })
    self.response.write(content)

  def send_message_to_collider(self, room_id, client_id, message):
    logging.info('Forwarding message to collider for room ' + room_id +
                 ' client ' + client_id)
    wss_url, wss_post_url = get_wss_parameters(self.request)
    url = wss_post_url + '/' + room_id + '/' + client_id
    result = urlfetch.fetch(url=url,
                            payload=message,
                            method=urlfetch.POST)
    if result.status_code != 200:
      logging.error(
          'Failed to send message to collider: %d' % (result.status_code))
      # TODO(tkchin): better error handling.
      self.error(500)
      return
    self.write_response('SUCCESS')

  def post(self, room_id, client_id):
    message_json = self.request.body
    result = save_message_from_client(
        self.request.host_url, room_id, client_id, message_json)
    if result['error'] is not None:
      self.write_response(result['error'])
      return
    self.write_response('SUCCESS')
    if result['saved']:
      logging.info('Saving message from client ' + client_id +
                   ' for room ' + room_id)
      return

    # Other client registered, forward to collider. Do this outside the lock.
    # Note: this may fail in local dev server due to not having the right
    # certificate file locally for SSL validation.
    # Note: loopback scenario follows this code path.
    # TODO(tkchin): consider async fetch here.
    self.send_message_to_collider(room_id, client_id, message_json)

class RegisterPage(webapp2.RequestHandler):
  def write_response(self, result, params, messages):
    # TODO(tkchin): Clean up response format. For simplicity put everything in
    # params for now.
    params['messages'] = messages
    self.response.write(json.dumps({
      'result': result,
      'params': params
    }))

  def write_room_parameters(self, room_id, client_id, messages, is_initiator):
    params = get_room_parameters(self.request, room_id, client_id, is_initiator)
    self.write_response('SUCCESS', params, messages)

  def post(self, room_id):
    client_id = generate_random(8)
    is_loopback = self.request.get('debug') == 'loopback'
    result = add_client_to_room(
        self.request.host_url, room_id, client_id, is_loopback)
    if result['is_full']:
      logging.info('Room ' + room_id + ' is full.')
      self.write_response('FULL', {}, [])
      return
    if not result['success']:
      self.write_response('ERROR', {}, [])
      return

    self.write_room_parameters(
        room_id, client_id, result['messages'], result['is_initiator'])
    logging.info('User ' + client_id + ' registered in room ' + room_id)
    logging.info('Room ' + room_id + ' has state ' + result['room_state'])

class MainPage(webapp2.RequestHandler):
  def get(self):
    """Redirects to a room page."""
    room_id = generate_random(8)
    redirect = '/r/' + room_id
    redirect = append_url_arguments(self.request, redirect)
    self.redirect(redirect)
    logging.info('Redirecting visitor to base URL to ' + redirect)

class RoomPage(webapp2.RequestHandler):
  def write_response(self, target_page, params={}):
    template = jinja_environment.get_template(target_page)
    content = template.render(params)
    self.response.out.write(content)

  def get(self, room_id):
    """Renders index.html or full.html."""
    # Check if room is full.
    room = memcache.get(
        get_memcache_key_for_room(self.request.host_url, room_id))
    if room is not None:
      logging.info('Room ' + room_id + ' has state ' + str(room))
      if room.get_occupancy() >= 2:
        logging.info('Room ' + room_id + ' is full')
        self.write_response('full.html')
        return
    # Parse out room parameters from request.
    params = get_room_parameters(self.request, room_id, None, None)
    self.write_response('index.html', params)

app = webapp2.WSGIApplication([
    ('/', MainPage),
    ('/bye/(\w+)/(\w+)', ByePage),
    ('/message/(\w+)/(\w+)', MessagePage),
    ('/register/(\w+)', RegisterPage),
    # TODO(jiayl): Remove support of /room/ when all clients are updated.
    ('/room/(\w+)', RoomPage),
    ('/r/(\w+)', RoomPage),
], debug=True)
