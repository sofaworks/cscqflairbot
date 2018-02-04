#!/usr/bin/env python

# This script creates a bot that responds to private messages for flair requests

import os
import itertools

from collections import namedtuple

import praw

USER_AGENT = 'r/cscareerquestions cscqflairbot v1.0 by u/SofaAssassin'

FlairMapping = namedtuple('FlairMapping', ['karma', 'flair_class'])

FLAIR_MAPPINGS = sorted([FlairMapping(k, 'over-{}-karma'.format(k))
    for k in (500, 1000, 3000, 5000, 10000, 20000)], key=lambda fm: fm.karma, reverse=True)


def get_environment_configuration():
    '''Get configuration values specified in environment variables'''
    configuration = {
        'USER_AGENT': os.getenv('BOT_USER_AGENT', USER_AGENT),
        'CLIENT_ID': os.environ['BOT_CLIENT_ID'],
        'CLIENT_SECRET': os.environ['BOT_CLIENT_SECRET'],
        'REDDIT_USERNAME': os.environ['BOT_USERNAME'],
        'REDDIT_PASSWORD': os.environ['BOT_PASSWORD'],
        'SUBREDDIT': os.getenv('FLAIR_SUBREDDIT', 'cscareerquestions')
    }
    return configuration


class FlairBot:
    # the flairs we care about
    def __init__(self, configuration):
        self.reddit = praw.Reddit(user_agent=configuration['USER_AGENT'],
                client_id=configuration['CLIENT_ID'],
                client_secret=configuration['CLIENT_SECRET'],
                username=configuration['REDDIT_USERNAME'],
                password=configuration['REDDIT_PASSWORD'])

        # The subreddit that flairs will be based on
        self.subreddit = configuration['SUBREDDIT']

        self.send_confirmations = True
        #self.use_comment_karma = True
        #self.use_submission_karma = True

    def check_pms(self):
        '''Check bot's unread PMs - we only care about PMs with the title "Flair Me"'''
        flair_requests = dict()
        ignored_messages = []
        for msg in self.reddit.inbox.unread(limit=None):
            author = msg.author.name
            if (msg.subject.strip().lower() == 'flair me') and (author not in flair_requests):
                flair_requests[author] = msg
            else:
                ignored_messages.append(msg)
        self.reddit.inbox.mark_read(ignored_messages)

        # now process flair_requests
        self.process_flair_requests(flair_requests)

    def calculate_subreddit_karma(self, redditor):
        total_karma = 0
        for thing in itertools.chain(redditor.comments.top('all'), redditor.submissions.top('all')):
            if thing.subreddit.display_name == self.subreddit:
                total_karma += thing.score
        return total_karma

    def process_flair_requests(self, flair_requests):
        '''Given a map of users and their messages, check for their
        flair level'''
        sub = self.reddit.subreddit(self.subreddit)
        for author, msg in flair_requests.items():
            karma = self.calculate_subreddit_karma(msg.author)
            # now use this to determine what tier it is
            flair_type = None
            for flair in FLAIR_MAPPINGS:
                if karma >= flair.karma:
                    flair_type = flair
                    break

            if not flair_type:
                # send a PM and say nothing will change
                print("No flair lol")
                msg.reply('Calculated Karma: **{}**. Too low for flair.'.format(karma))
            else:
                # get the current flair for the user
                current_flair = next(sub.flair(redditor=author))
                flair_class = current_flair['flair_css_class']
                flair_text = current_flair['flair_text']
                set_new_flair = False

                if flair_class:
                    # if flair_class is None but flair_type isn't, just set flair_type
                    if flair_class == flair_type.flair_class:
                        msg.reply('Calculated Karma: **{}**. Flair class is same as what you have now, so no changes.'.format(karma))
                    else: # determine if the new flair class is higher than the current one
                        current_flair_karma_class = int(flair_class.split('-')[1])
                        if current_flair_karma_class > flair_type.karma:
                            # our new flair is worse than the old one, so don't change it
                            msg.reply('Calculated Karma: **{}**. New flair would be worse than your current, so no changes.'.format(karma))
                        else:
                            set_new_flair = True
                else:
                    set_new_flair = True

            if set_new_flair:
                # change flair class for user
                sub.flair.set(author, css_class=flair_type.flair_class, text=flair_text)
                msg.reply('Calculated Karma: **{}**. New flair set for karma level {}+'.format(karma, flair_type.karma))
            msg.mark_read()



if __name__ == '__main__':
    fb = FlairBot(get_environment_configuration())
    fb.check_pms()
