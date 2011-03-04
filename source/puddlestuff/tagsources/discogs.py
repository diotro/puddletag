# -*- coding: utf-8 -*-
#Example tutorial for writing a tag source plugin using Amazon's webservice API.

#The important stuff is at the bottom in the Amazon class.
#Comments (or you've created a tag source you'd like
#to share) can be directed at concentricpuddle@gmail.com

#Imports and constants.
#-----------------------------------------------------------
import base64, hmac, hashlib, os, re, time, urllib2, urllib, xml, re

from xml.dom import minidom
import sys

from puddlestuff.constants import CHECKBOX, COMBO, SAVEDIR, TEXT
from puddlestuff.tagsources import (write_log, set_status, RetrievalError,
    urlopen, parse_searchstring, iri_to_uri)
import puddlestuff.tagsources
from puddlestuff.audioinfo import DATA
import urllib2, gzip, cStringIO, pdb, socket
from copy import deepcopy
from puddlestuff.util import translate

R_ID = 'discogs_rid'

api_key = 'c6e33897b6'
search_url = 'http://www.discogs.com/search?type=releases&q=%s&f=xml&api_key=c6e33897b6'
album_url = 'http://www.discogs.com/release/%s?f=xml&api_key=c6e33897b6'

SMALLIMAGE = '#smallimage'
LARGEIMAGE = '#largeimage'

image_types = [SMALLIMAGE, LARGEIMAGE]

ALBUM_KEYS = {
    'title': 'album',
    'uri': 'discogs_uri',
    'summary': 'discogs_summary',
    'released': 'year',
    'notes': 'discogs_notes'}

TRACK_KEYS = {
    'position': 'track',
    'duration': '__length',
    'notes': 'discogs_notes'}

def convert_dict(d, keys=TRACK_KEYS):
    d = deepcopy(d)
    for key in keys:
        if key in d:
            d[keys[key]] = d[key]
            del(d[key])
    return d

IMAGEKEYS = {
    'SmallImage': SMALLIMAGE,
    'LargeImage': LARGEIMAGE}

def find_id(tracks, field=None):
    if not field:
        return
    for track in tracks:
        if field in track:
            value = track[field]
            if isinstance(value, basestring):
                return value
            else:
                return value[0]

def is_release(element):
    return element.attributes['type'].value == 'release'

def node_to_dict(node):
    ret = {}
    for child in node.childNodes:
        if child.nodeType == child.TEXT_NODE:
            continue
        text_node = child.firstChild
        if text_node is None:
            continue
        if text_node.nodeType == text_node.TEXT_NODE:
            ret[child.tagName] = text_node.data
    return ret

def get_text(node):
    """Returns the textual data in a node."""
    try:
        return node.firstChild.data
    except AttributeError:
        return

def keyword_search(keywords):
    write_log(translate("Discogs", 'Retrieving search results for keywords: %s') % keywords)
    keywords = re.sub('(\s+)', u'+', keywords)
    url = search_url % keywords
    text = urlopen(url)
    return parse_search_xml(text)

def parse_album_xml(text):
    """Parses the retrieved xml for an album and get's the track listing."""
    doc = minidom.parseString(text)
    info = {}
    info['artist'] = [node_to_dict(e)['name'] for e in
        doc.getElementsByTagName('artists')[0].childNodes if node_to_dict(e)]

    labels = doc.getElementsByTagName('labels')
    if labels:
        for label in labels[0].childNodes:
            try:
                info['label'] = label.attributes['name'].value
                info['discogs_catno'] = label.attributes['catno'].value
            except (AttributeError, KeyError):
                continue

    formats = doc.getElementsByTagName('formats')
    if formats:
        for format in formats[0].childNodes:
            try:
                info['discogs_format'] = format.attributes['name'].value
                info['discs'] = format.attributes['qty'].value
            except (AttributeError, IndexError, ValueError):
                pass
            try:
                info['discogs_format_desc'] = filter(None,
                    [get_text(z) for z in format.childNodes[0].childNodes])
            except (AttributeError, IndexError, ValueError):
                continue

    extras = doc.getElementsByTagName('extraartists')
    if extras:
        ex_artists = [node_to_dict(z) for z  in extras[0].childNodes]
        info['involvedpeople'] = u';'.join(u'%s:%s' % (e['name'], e['role'])
            for e in ex_artists)

    try:
        info['genre'] = filter(None, [get_text(z) for z in
            doc.getElementsByTagName('genres')[0].childNodes])
    except IndexError:
        pass

    try:
        info['style'] = filter(None, [get_text(z) for z in
            doc.getElementsByTagName('styles')[0].childNodes])
    except IndexError:
        pass

    text_keys = ['notes', 'country', 'released', 'title']

    for key in text_keys:
        try:
            info[key] = get_text(doc.getElementsByTagName(key)[0])
        except IndexError:
            continue

    images = doc.getElementsByTagName('images')
    if images:
        image_list = []
        for image in images[0].childNodes:
            d = dict(image.attributes.items())
            if not d:
                continue
            if d['type'] == 'primary':
                image_list.insert(0, (d['uri'], d['uri150']))
            else:
                image_list.append((d['uri'], d['uri150']))
        info['#cover-url'] = image_list

    tracklist = doc.getElementsByTagName('tracklist')[0]
    return convert_dict(info, ALBUM_KEYS), filter(None,
        [convert_dict(node_to_dict(z)) for z in tracklist.childNodes])

def parse_search_xml(text):
    """Parses the xml retrieved after entering a search query. Returns a
    list of the albums found.
    """
    try:
        doc = minidom.parseString(text)
    except xml.parsers.expat.ExpatError:
        write_log(text)
        raise RetrievalError(translate("Discogs",
            'Invalid XML was returned. See log'))
    exact = doc.getElementsByTagName('exactresults')
    results = []
    if exact:
        results = filter(is_release, exact[0].getElementsByTagName('result'))

    if not results:
        search_results = doc.getElementsByTagName('searchresults')
        results = filter(is_release, search_results[0].getElementsByTagName('result'))

    ret = []

    for result in results:
        info = node_to_dict(result)
        info['#r_id'] = re.search('\d+$', info['uri']).group()
        info[R_ID] = info['#r_id']
        info = convert_dict(info, ALBUM_KEYS)
        ret.append(info)
    return ret

def retrieve_album(info, image=LARGEIMAGE):
    """Retrieves album from the information in info.
    image must be either one of image_types or None.
    If None, no image is retrieved."""
    if isinstance(info, (int, long)):
        r_id = unicode(info)
        info = {}
        write_log(translate("Discogs", 'Retrieving using Release ID: %s') % r_id)
    elif isinstance(info, basestring):
        r_id = info
        info = {}
        write_log(translate("Discogs", 'Retrieving using Release ID: %s') % r_id)
    else:
        r_id = info['#r_id']
        write_log(translate("Discogs", 'Retrieving album %s') % (info['album']))
    
    xml = urlopen(album_url % r_id)

    ret = parse_album_xml(xml)

    info = deepcopy(info)
    info.update(ret[0])

    if image in image_types and '#cover-url' in info:
        data = []
        for large, small in info['#cover-url']:
            if image == LARGEIMAGE:
                write_log(translate("Discogs", 'Retrieving cover: %s') % large)
                data.append({DATA: urlopen(large)})
            else:
                write_log(translate("Discogs", 'Retrieving cover: %s') % small)
                data.append({DATA: urlopen(small)})
        info.update({'__image': data})
    return info, ret[1]

def search(artist=None, album=None):
    if artist and album:
        keywords = u' '.join([artist, album])
    elif artist:
        keywords = artist
    else:
        keywords = album
    return keyword_search(keywords)


def urlopen(url):
    url = iri_to_uri(url)
    request = urllib2.Request(url)
    request.add_header('Accept-Encoding', 'gzip')
    if puddlestuff.tagsources.user_agent:
        request.add_header('User-Agent', puddlestuff.tagsources.user_agent)
    try:
        data = urllib2.urlopen(request).read()
    except urllib2.URLError, e:
        try:
            msg = u'%s (%s)' % (e.reason.strerror, e.reason.errno)
        except AttributeError:
            msg = unicode(e)
        raise RetrievalError(msg)
    except socket.error:
        msg = u'%s (%s)' % (e.strerror, e.errno)
        raise RetrievalError(msg)
    except EnvironmentError, e:
        msg = u'%s (%s)' % (e.strerror, e.errno)
        raise RetrievalError(msg)

    try: data = gzip.GzipFile(fileobj = cStringIO.StringIO(data)).read()
    except IOError: "Gzipped data not returned."

    i = 0
    filename = os.path.join('/home/keith/Desktop', unicode(i))
    while not os.path.exists(filename):
        i += 1
        filename = os.path.join('/home/keith/Desktop', unicode(i))
    f = open(filename, 'w')
    f.write(data)
    f.close()
    return data


class Discogs(object):
    name = 'Discogs.com'
    group_by = [u'album', u'artist']
    tooltip = translate("Discogs", """<p>Enter search parameters here. If empty,
        the selected files are used.</p>
        <ul>
        <li><b>artist;album</b>
        searches for a specific album/artist combination.</li>
        <li>To list the albums by an artist leave off the album part,
        but keep the semicolon (eg. <b>Ratatat;</b>).
        For a album only leave the artist part as in
        <b>;Resurrection.</li>
        <li>Using <b>:r id</b> will retrieve the album with Discogs
        ID <b>id</b>.</li>
        <li>Entering keywords <b>without a semi-colon (;)</b> will
         do a Discogs album search using those keywords.</li>
        </ul>""")

    def __init__(self):
        super(Discogs, self).__init__()
        self._getcover = True
        self.covertype = 1

        self.preferences = [
            [translate('Discogs', 'Retrieve Cover'), CHECKBOX, True],
            [translate("Discogs", 'Cover size to retrieve'), COMBO,
                [[translate("Discogs", 'Small'),
                    translate("Discogs", 'Large')], 1]],
            [translate("Discogs", 'Field to use for discogs_id'), TEXT, R_ID],
            [translate("Discogs", 'API Key (Stored as plain-text. Leave empty to use default.)'),
                TEXT, ''],
            ]

    def keyword_search(self, text):

        if text.startswith(':r'):
            r_id = text[len(':r'):].strip()
            try:
                int(r_id)
                return [retrieve_album(r_id, self.covertype)]
            except TypeError:
                raise RetrievalError(translate("Discogs", 'Invalid Discogs Release ID'))
        try:
            params = parse_searchstring(text)
        except RetrievalError:
            return [(info, []) for info in keyword_search(text)]

        artists = [params[0][0]]
        album = params[0][1]
        return self.search(album, artists)

    def search(self, album, artists):

        if len(artists) > 1:
            artist = u'Various Artists'
        else:
            artist = [z for z in artists][0]

        if hasattr(artists, 'values'):
            write_log(translate("Discogs", 'Checking tracks for Discogs Album ID.'))
            tracks = []
            [tracks.extend(z) for z in artists.values()]
            album_id = find_id(tracks, R_ID)
            if not album_id:
                write_log(translate("Discogs", 'No Discogs ID found in tracks.'))
            else:
                write_log(translate("Discogs", 'Found Discogs ID: %s') % album_id)
                return [retrieve_album(album_id, self.covertype)]

        retrieved_albums = search(artist, album)
        return [(info, []) for info in retrieved_albums]

    def retrieve(self, info):
        if self._getcover:
            return retrieve_album(info, self.covertype)
        else:
            return retrieve_album(info, None)

    def applyPrefs(self, args):
        self._getcover = args[0]
        self.covertype = image_types[args[1]]
        global R_ID
        R_ID = args[2]
        global search_url
        global album_url
        if args[3]:
            search_url = 'http://www.discogs.com/search?type=releases&q=%s&f=xml&api_key=' + args[3]
            album_url = 'http://www.discogs.com/release/%s?f=xml&api_key=' + args[3]
        else:
            search_url = 'http://www.discogs.com/search?type=releases&q=%s&f=xml&api_key=' + api_key
            album_url = 'http://www.discogs.com/release/%s?f=xml&api_key=' + api_key

info = Discogs

if __name__ == '__main__':
    print parse_album_xml(open(sys.argv[1], 'r').read())

#print keyword_search('Minutes to midnight')