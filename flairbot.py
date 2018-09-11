#!/usr/bin/env python

# This script creates a bot that responds to private messages for flair requests

import os
import logging
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
    def __init__(self, configuration):
        self.reddit = praw.Reddit(user_agent=configuration['USER_AGENT'],
                client_id=configuration['CLIENT_ID'],
                client_secret=configuration['CLIENT_SECRET'],
                username=configuration['REDDIT_USERNAME'],
                password=configuration['REDDIT_PASSWORD'])

        # The subreddit that flairs will be based on
        self.subreddit = configuration['SUBREDDIT']

        self.send_confirmations = True
        self.use_comment_karma = True
        self.use_submission_karma = True


    def check_pms(self):
        '''Check bot's unread PMs - we only care about PMs with the
        title "Flair Me" or "Change Flair Text"'''
        flair_requests = dict()
        flair_text_changes = dict()
        ignored_messages = []
        for msg in self.reddit.inbox.unread(limit=None):
            if not msg.author:
                # Certain types of PMs (like mod invites) do not have an author object,
                # so just ignore those
                ignored_messages.append(msg)
                continue

            author = msg.author.name
            if (msg.subject.strip().lower() == 'flair me') and (author not in flair_requests):
                logging.info("request=CalculateFlair user={}".format(author))
                flair_requests[author] = msg
            elif (msg.subject.strip().lower() == 'change flair text') and (author not in flair_text_changes):
                logging.info("request=ChangeFlairText user={}".format(author))
                flair_text_changes[author] = msg
            else:
                ignored_messages.append(msg)
        self.reddit.inbox.mark_read(ignored_messages)

        # process flair text requests first, as they are
        # much faster to process
        self.process_flair_text_requests(flair_text_changes)

        # now process flair_requests, as these can take a long time
        # since it has to generate up to 40 API calls per user
        self.process_flair_requests(flair_requests)

    def change_flair_text(self, subreddit, redditor, new_flair_text):
        current_flair = next(subreddit.flair(redditor=redditor))
        flair_class = current_flair['flair_css_class']
        try:
            logging.info("action=ChangeFlairText user={} text={}".format(redditor, new_flair_text))
            subreddit.flair.set(redditor, new_flair_text, flair_class)
        except Exception as e:
            logging.exception("Problem occurred setting flair text for {}".format(redditor))
            return False
        return True


    def process_flair_text_requests(self, flair_text_requests):
        sub = self.reddit.subreddit(self.subreddit)
        for author, msg in flair_text_requests.items():
            # extract the first line
            flair_text = msg.body.splitlines()[0].strip()
            success = self.change_flair_text(sub, author, flair_text)
            if success:
                reply = "Flair text changed to: **{}**. Your flair color has not changed.".format(flair_text)
            else:
                reply = "There was a problem changing your flair text. Try again. If this keeps occurring, please contact the {} mods".format(self.subreddit)
            msg.reply(reply)
            msg.mark_read()


    def calculate_subreddit_karma(self, redditor, listing_type='top'):
        total_karma = 0
        if listing_type not in ('new', 'top'):
            logging.warn("Unsupported listing type {} passed for calculating subreddit karma".format(listing_type))
            raise TypeError("Unsupported listing type {}".format(listing_type))

        comment_method = getattr(redditor.comments, listing_type)
        submission_method = getattr(redditor.submissions, listing_type)
        for thing in itertools.chain(comment_method(limit=None), submission_method(limit=None)):
            if thing.subreddit.display_name == self.subreddit:
                total_karma += thing.score
        return total_karma


    def generate_flair_message(self, **kwargs):
        base_flair_message = ('Karma by **top posts**: **{top_karma}**  \n'
          'Karma by **new posts**: **{new_karma}**  \n'
          'Your highest karma was calculated using **{karma_type} posts**.  \n\n'
          '{msg}')

        return base_flair_message.format(**kwargs)


    def process_flair_requests(self, flair_requests):
        '''Given a map of users and their messages, check for their
        flair level'''

        sub = self.reddit.subreddit(self.subreddit)
        for author, msg in flair_requests.items():
            top_karma = self.calculate_subreddit_karma(msg.author, 'top')
            new_karma = self.calculate_subreddit_karma(msg.author, 'new')

            # now use this to determine what tier it is
            if top_karma > new_karma:
                karma = top_karma
                karma_type = 'top'
            else:
                karma = new_karma
                karma_type = 'new'

            flair_type = None
            for flair in FLAIR_MAPPINGS:
                if karma >= flair.karma:
                    flair_type = flair
                    break

            fmt_dict = {
                'karma_type': karma_type,
                'top_karma': top_karma,
                'new_karma': new_karma
            }

            set_new_flair = False
            if not flair_type:
                # send a PM and say nothing will change
                msg.reply(self.generate_flair_message(**fmt_dict, msg='Your calculated karma was too low for flair'))
            else:
                # get the current flair for the user
                current_flair = next(sub.flair(redditor=author))
                flair_class = current_flair['flair_css_class']
                flair_text = current_flair['flair_text']

                if flair_class:
                    # if flair_class is None but flair_type isn't, just set flair_type
                    if flair_class == flair_type.flair_class:
                        msg.reply(self.generate_flair_message(**fmt_dict,
                                      msg='Flair class is same as what you have now, so no changes.'))

                    else: # determine if the new flair class is higher than the current one
                        current_flair_karma_class = int(flair_class.split('-')[1])
                        if current_flair_karma_class > flair_type.karma:
                            # our new flair is worse than the old one, so don't change it
                            msg.reply(self.generate_flair_message(**fmt_dict, msg='New flair would be worse than current flair, so no changes.'))
                        else:
                            set_new_flair = True
                else:
                    set_new_flair = True

            if set_new_flair:
                # change flair class for user
                logging.info("action=ChangeFlairClass user={} class={}".format(author, flair_type.flair_class))
                sub.flair.set(author, css_class=flair_type.flair_class, text=flair_text)
                msg.reply(self.generate_flair_message(**fmt_dict, msg='Setting new flair for karma level {}+'.format(flair_type.karma)))
            msg.mark_read()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    fb = FlairBot(get_environment_configuration())
    fb.check_pms()
