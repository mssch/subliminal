# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import collections
import io
import logging
import operator
import os.path
import babelfish
from .providers import ProviderPool
from .subtitle import get_subtitle_path
from random import randint

logger = logging.getLogger(__name__)

# Agent List
AGENT_LIST = (
    'Mozilla/5.0 (Windows NT 6.3; rv:36.0) Gecko/20100101 Firefox/36.0',
    'Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2228.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2227.1 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10; rv:33.0) Gecko/20100101 Firefox/33.0',
    'Mozilla/5.0 (X11; Linux i586; rv:31.0) Gecko/20100101 Firefox/31.0',
    'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:31.0) Gecko/20130401 Firefox/31.0',
    'Mozilla/5.0 (Windows NT 5.1; rv:31.0) Gecko/20100101 Firefox/31.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2227.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2227.0 Safari/537.36',
    'Mozilla/5.0 (compatible, MSIE 11, Windows NT 6.3; Trident/7.0; rv:11.0) like Gecko',
    'Mozilla/5.0 (compatible; MSIE 10.0; Windows NT 6.1; WOW64; Trident/6.0)',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.75.14 (KHTML, like Gecko) Version/7.0.3 Safari/7046A194A',
    'Mozilla/5.0 (iPad; CPU OS 6_0 like Mac OS X) AppleWebKit/536.26 (KHTML, like Gecko) Version/6.0 Mobile/10A5355d Safari/8536.25',
)

# Returns a random agent to use from the list above
RANDOM_USER_AGENT = AGENT_LIST[randint(0, len(AGENT_LIST)-1)]

def list_subtitles(videos, languages, providers=None, provider_configs=None):
    """List subtitles for `videos` with the given `languages` using the specified `providers`

    :param videos: videos to list subtitles for
    :type videos: set of :class:`~subliminal.video.Video`
    :param languages: languages of subtitles to search for
    :type languages: set of :class:`babelfish.Language`
    :param providers: providers to use, if not all
    :type providers: list of string or None
    :param provider_configs: configuration for providers
    :type provider_configs: dict of provider name => provider constructor kwargs or None
    :return: found subtitles
    :rtype: dict of :class:`~subliminal.video.Video` => [:class:`~subliminal.subtitle.Subtitle`]

    """
    subtitles = collections.defaultdict(list)
    with ProviderPool(providers, provider_configs) as pp:
        for video in videos:
            logger.info('Listing subtitles for %r', video)
            video_subtitles = pp.list_subtitles(video, languages)
            logger.info('Found %d subtitles total', len(video_subtitles))
            subtitles[video].extend(video_subtitles)
    return subtitles


def download_subtitles(subtitles, provider_configs=None):
    """Download subtitles

    :param subtitles: subtitles to download
    :type subtitles: list of :class:`~subliminal.subtitle.Subtitle`
    :param provider_configs: configuration for providers
    :type provider_configs: dict of provider name => provider constructor kwargs or None

    """
    with ProviderPool(provider_configs=provider_configs) as pp:
        for subtitle in subtitles:
            logger.info('Downloading subtitle %r', subtitle)
            pp.download_subtitle(subtitle)


def download_best_subtitles(videos, languages, providers=None, provider_configs=None, min_score=0,
                            hearing_impaired=False, single=False):
    """Download the best subtitles for `videos` with the given `languages` using the specified `providers`

    :param videos: videos to download subtitles for
    :type videos: set of :class:`~subliminal.video.Video`
    :param languages: languages of subtitles to download
    :type languages: set of :class:`babelfish.Language`
    :param providers: providers to use for the search, if not all
    :type providers: list of string or None
    :param provider_configs: configuration for providers
    :type provider_configs: dict of provider name => provider constructor kwargs or None
    :param int min_score: minimum score for subtitles to download
    :param bool hearing_impaired: download hearing impaired subtitles
    :param bool single: do not download for videos with an undetermined subtitle language detected

    """
    downloaded_subtitles = collections.defaultdict(list)
    with ProviderPool(providers, provider_configs) as pp:
        for video in videos:
            # filter
            if single and babelfish.Language('und') in video.subtitle_languages:
                logger.debug('Skipping video %r: undetermined language found')
                continue

            # list
            logger.info('Listing subtitles for %r', video)
            video_subtitles = pp.list_subtitles(video, languages)
            logger.info('Found %d subtitles total', len(video_subtitles))

            # download
            downloaded_languages = set()
            for subtitle, score in sorted([(s, s.compute_score(video)) for s in video_subtitles],
                                          key=operator.itemgetter(1), reverse=True):
                if score < min_score:
                    logger.info('No subtitle with score >= %d', min_score)
                    break
                if subtitle.hearing_impaired != hearing_impaired:
                    logger.debug('Skipping subtitle: hearing impaired != %r', hearing_impaired)
                    continue
                if subtitle.language in downloaded_languages:
                    logger.debug('Skipping subtitle: %r already downloaded', subtitle.language)
                    continue
                logger.info('Downloading subtitle %r with score %d', subtitle, score)
                if pp.download_subtitle(subtitle):
                    downloaded_languages.add(subtitle.language)
                    downloaded_subtitles[video].append(subtitle)
                if single or downloaded_languages == languages:
                    logger.debug('All languages downloaded')
                    break
    return downloaded_subtitles


def save_subtitles(subtitles, single=False, directory=None, encoding=None):
    """Save subtitles on disk next to the video or in a specific folder if `folder_path` is specified

    :param bool single: download with .srt extension if ``True``, add language identifier otherwise
    :param directory: path to directory where to save the subtitles, if any
    :type directory: string or None
    :param encoding: encoding for the subtitles or ``None`` to use the original encoding
    :type encoding: string or None

    """
    for video, video_subtitles in subtitles.items():
        saved_languages = set()
        for video_subtitle in video_subtitles:
            if video_subtitle.content is None:
                logger.debug('Skipping subtitle %r: no content', video_subtitle)
                continue
            if video_subtitle.language in saved_languages:
                logger.debug('Skipping subtitle %r: language already saved', video_subtitle)
                continue
            subtitle_path = get_subtitle_path(video.name, None if single else video_subtitle.language)
            if directory is not None:
                subtitle_path = os.path.join(directory, os.path.split(subtitle_path)[1])
            logger.info('Saving %r to %r', video_subtitle, subtitle_path)
            if encoding is None:
                with io.open(subtitle_path, 'wb') as f:
                    f.write(video_subtitle.content)
            else:
                with io.open(subtitle_path, 'w', encoding=encoding) as f:
                    f.write(video_subtitle.text)
            saved_languages.add(video_subtitle.language)
            if single:
                break
