import random
import re
import urllib2

from collections import defaultdict

from hamper.interfaces import ChatCommandPlugin, Command
from hamper.utils import ude, uen

from sqlalchemy import Column, Integer, String, desc
from sqlalchemy.ext.declarative import declarative_base

SQLAlchemyBase = declarative_base()


class CardsAgainstHumanity(ChatCommandPlugin):
    """ Play the classic card game Cards Against Humanity """

    name = 'cah'

    priority = 1

    NUM_CARDS = 8

    short_desc = 'Play the classic game Cards Against Humanity.'
    long_desc = ('!join - Joins the game.\n'
                 '!leave - Leaves the game.\n'
                 '!play <card #> - Plays a card. May play more than one.\n'
                 '!winner <answer #> - Chooses a winner for a given prompt.')

    player_queue = []
    dealer_queue = []

    black_discard = []
    white_discard = []

    state = "join"

    players = defaultdict(list)
    prompt = ""
    dealer = ""

    #it is inefficient to build this list everytime we need it.
    avail_players = []
    answers= defaultdict(list)

    already_in = "{0}, you are already a part of the game!"
    not_in = "{0}, you are not a part of the game!"

    def setup(self, loader):
        super(CardsAgainstHumanity, self).setup(loader)
        self.db = loader.db
        SQLAlchemyBase.metadata.create_all(self.db.engine)

        ct = self.db.session.query(CardTable)

        # Update db if it's empty.
        if ct.count() == 0:
            self.flush_db()

        self.whites = ct.filter_by(color="white").all()
        self.blacks = ct.filter_by(color="black").all()

        random.shuffle(self.whites) # Erry' day I'm shufflin'!
        random.shuffle(self.blacks)

    def remove_player(self, player):
        # Return cards to discard
        self.white_discard += self.players[player]
        # Remove player
        del(self.players[player])
        while player in self.dealer_queue:
            self.dealer_queue.remove(player)

    def give_point(self, user):
        winner = self.db.session.query(CAHTable).filter_by(user=user).first()
        try:
            winner.score += 1
        except AttributeError:
            self.db.session.add(CAHTable(user, score=1))
        self.db.session.commit()

    def deal(self, user):
        while len(self.players[user]) < self.NUM_CARDS:
            self.players[user].append(self.whites.pop(0))

    def reset(self, bot, comm):
        # Fill black discard
        self.black_discard.append(self.prompt)

        # Fill white discard
        for p in self.avail_players:
            print p
            for c in self.answers[p]:
                self.white_discard.append(c)

        self.answers.clear()

        # Put discards back in deck
        if len(self.black_discard) > len(self.blacks) * 2:
            self.blacks += self.black_discard
            random.shuffle(self.blacks)
            self.black_discards = []

        if len(self.white_discard) > len(self.whites) * 2:
            self.whites += self.white_discard
            random.shuffle(self.whites)
            self.white_discards = []

        # Fill up dealer_queue 
        if len(self.dealer_queue) < len(self.players):
            self.dealer_queue += [p for p in self.players]

        for p in self.player_queue:
            self.deal(p)
        del(self.player_queue[:])

        if len(self.players) > 2:
            self.prep_play(bot, comm)
        else:
            self.state = "join"
            bot.reply(comm, self.plugin.current_players())

    def prep_play(self, bot, comm):
        self.state = "play"

        if not self.dealer_queue:
            self.dealer_queue += self.players

        self.dealer = self.dealer_queue.pop(0)
        self.prompt = self.blacks.pop(0).desc.encode('utf-8')
        self.avail_players = [p for p in self.players if p != self.dealer]

        bot.reply(comm, "[*] {0} reads: {1}".format(self.dealer, self.prompt))
        bot.reply(comm, "[*] Type: \"play <card #>\" to fill blanks. Multiple "
                        "cards are played with \"play <card #> <card #>\".")

        for p in self.players:
            self.deal(p)

        # Show current hand to players
        for p in self.avail_players:
            self.show_hand(bot, p)

    def show_top_scores(self, bot, comm, current_players=True):
        if current_players:
            top = self.db.session.query(CAHTable).filter(
                CAHTable.user.in_(self.players)
            ).order_by(CAHTable.score.desc()).all()
        else:
            top = self.db.session.query(CAHTable).order_by(
                        CAHTable.score.desc().all()
                    )
        scores_str = '{:^14} {:^14}\n____________________________'
        bot.reply(comm, scores_str.format('User', 'Score'))
        scores_str = '{:^14}|{:^14}'
        num_top = 5 if len(top) > 4 else len(top)
        scores = '\n'.join([scores_str.format(top[x].user, str(top[x].score))
                            for x in xrange(num_top)])
        bot.reply(comm, scores)

    def flush_db(self):
        """
        Clear out old cards, and bring in new ones.
        """
        self.db.session.query(CardTable).delete()

        url = "http://web.engr.oregonstate.edu/~johnsdea/"

        whites_txt = urllib2.urlopen(url + "whites.txt").read().split("\n")
        blacks_txt = urllib2.urlopen(url + "blacks.txt").read().split("\n")
        new_whites = map(self.format_white, whites_txt)
        for white in new_whites:
            self.db.session.add(CardTable(unicode(white, 'utf-8'), "white"))
        new_blacks = map(self.init_black, blacks_txt)
        for black in new_blacks:
            self.db.session.add(CardTable(unicode(black, 'utf-8'), "black"))

        self.db.session.commit()

    def format_white(self, card):
        card = card.strip("\n")
        if card.endswith("."):
            card = card[:-1]
        return card

    def init_black(self, card):
        card = card.strip("\n")
        if "__________" not in card:
            card += " __________."
        return card

    def format_black(self, card):
        card.strip("\n")
        for x in xrange(card.count("__________")):
            card = card.replace("__________", "{" + str(x) + "}", 1)
        return card

    def show_hand(self, bot, name):
        print "Showing hand for: " + name
        cards = '. '.join((str(x + 1) + ": " + self.players[name][x].desc.encode('utf-8')
                            for x in xrange(self.NUM_CARDS)))

        bot.notice(name, "Your hand is: \n[" + cards + "]")

    def current_players(self):
        players = ', '.join(p for p in self.players) + '.'
        return "[*] Current players: " + players

    class Join(Command):
        """ Join/Queue up for a game """

        regex = r'^join ?$'

        name = 'join'
        short_desc = 'join - Joins the game.'
        long_desc = 'Joins the current Cards Against Humanity game.'

        def command(self, bot, comm, groups):
            print "intercepted join command!"
            user = comm['user']
            if user in self.plugin.players:
                return bot.reply(comm, self.plugin.already_in.format(user))
            elif user in self.plugin.player_queue:
                return bot.reply(comm, '{0}, you are already in the queue!'.format(user))

            # This is only when the game is first starting.
            if self.plugin.state == "join":
                self.plugin.deal(user)
                if len(self.plugin.players) > 2:
                    bot.reply(comm, "[*] {0} has joined the game! There are "
                                "now enough players to play!".format(user))
                    self.plugin.prep_play(bot, comm)
                else:
                    bot.reply(comm, "[*] {0} has joined the game! Waiting for "
                                "{1} more player(s).".format(
                                    user, 3 - len(self.plugin.players)))
            else:
                bot.reply(comm, "[*] {0} has joined the queue!".format(user))
                self.plugin.player_queue.append(user)
            bot.reply(comm, self.plugin.current_players())

    class Leave(Command):
        name = 'leave'
        regex = r'^leave ?$'

        short_desc = 'leave - Leaves the game.'
        long_desc = 'Leaves the current Cards Against Humanity game.'

        def command(self, bot, comm, groups):
            print "intercepted leave command!"
            user = comm['user']

            if (user not in self.plugin.players and
                    user not in self.plugin.player_queue):
                return self.plugin.not_in.format(user)

            self.plugin.remove_player(user)
            bot.reply(comm, "{0} has left the game!".format(user))

            if self.plugin.state == "play":
                if user in self.plugin.avail_players:
                    self.plugin.avail_players.remove(user)
                elif user == self.plugin.dealer:
                    bot.reply(comm, "Game restarting... dealer left.")
                    self.plugin.reset(comm, bot)
                elif len(self.plugin.players) < 3:
                    bot.reply(comm, "There are less than 3 players playing "
                                "now. Waiting for more players...")
                    self.plugin.reset(comm, bot)
            elif self.plugin.state == "winner":
                if user == self.plugin.dealer:
                    bot.reply(comm, "Game restarting... Dealer left.")
                    self.plugin.reset(comm, bot)

            bot.reply(comm, self.plugin.current_players())

    class Play(Command):
        name = 'play'
        regex = r'^play (.*)'

        short_desc = 'play - Plays a card from your hand.'
        long_desc = ('Play a card from your card with "!play <card #>".'
                     'Multiple cards may be played with "!play <card #> '
                     '<card #>".')

        def command(self, bot, comm, groups):
            print "intercepted play command!"
            nums_re = '\d'
            user = comm['user']
            if user not in self.plugin.players:
                return self.plugin.not_in.format(user)
            elif user == self.plugin.dealer:
                return bot.reply(comm, "{0}, you are the dealer!".format(user))
            elif user in self.plugin.answers:
                return bot.reply(comm, "{0}, you already submitted your cards!".format(user))

            print groups

            try:
                indices = map(int, groups[0].split(" "))
            except:
                return bot.reply(comm, "{0}, you didn't provide hand index(s) for cards!"
                            .format(user))

            print "indices="
            print indices

            if len(indices) != self.plugin.prompt.count("__________"):
                return ("{0}, you didn't provide the correct amount"
                            "of cards!".format(user))

            self.plugin.answers[user] = [self.plugin.players[user][i - 1].desc.encode('utf-8')
                                    for i in indices]

            # Don't change index of cards that are being removed..
            for index in reversed(sorted(indices, key=lambda x: x)):
                self.plugin.players[user].pop(index - 1)

            if len(self.plugin.answers) == len(self.plugin.avail_players):
                bot.reply(comm, "[*] All players have turned in their cards.")
                for x in xrange(len(self.plugin.avail_players)):
                    text = ("[*] [Answer #" + str(x) + "]: " +
                            self.plugin.format_black(self.plugin.prompt).format(
                                *self.plugin.answers[self.plugin.avail_players[x]]
                            ))
                    text = text + "." if not text.endswith(".") else text
                    bot.reply(comm, text)
                bot.reply(comm, "{0}, please choose a winner with "
                            "\"winner <answer #>\".".format(self.plugin.dealer))
                self.plugin.state = "winner"

    class Winner(Command):
        name = 'winner'
        regex = r'^winner (.*)'

        short_desc = 'winner - Chooses a winner.'
        long_desc = ('Choose a winner from the available options with "!winner'
                     ' <card #>".')

        def command(self, bot, comm, groups):
            print "intercepted winner command!"
            user = comm['user']
            if self.plugin.state != "winner":
                return bot.reply(comm, "{0}, it is not time to choose a "
                            "winner!".format(user))
            elif user != self.plugin.dealer:
                return bot.reply(comm, "{0}, you may not choose the winner! "
                                    .format(user))

            winner_re = r'^winner (\d)'
            winner_ind = int(re.match(winner_re, comm['message'], re.S).group(1))
            winner = ""
            for i, player in enumerate(self.plugin.avail_players):
                print "%d: %s" % (i, player)
                if i == winner_ind:
                    winner = player
            if not winner:
                return bot.reply(comm, "{0}, that answer doesn't exist!"
                            .format(user))

            bot.reply(comm, "{0}, you won this round! Congrats!".format(winner))

            self.plugin.give_point(winner)
            self.plugin.show_top_scores(bot, comm)
            self.plugin.reset(bot, comm)

class CardTable(SQLAlchemyBase):
    """
    This is only for persistant storage of all cards. More can also be 
    added through commands in this manner.
    """

    __tablename__ = 'cah_cards'

    id = Column(Integer, primary_key=True)
    desc = Column(String)
    color = Column(String)

    def __init__(self, desc, color):
        self.desc = desc
        self.color = color

    def __repr__(self):
        print self.desc
        return self.desc


class CAHTable(SQLAlchemyBase):
    """
    For storing scores for everyone who plays the game.
    """

    __tablename__ = 'cah'

    user = Column(String, primary_key=True)
    score = Column(Integer)

    def __init__(self, user, score=0):
        self.user = user
        self.score = score

    def __repr__(self):
        return "%s: %d" % self.user, self.score


cah = CardsAgainstHumanity()
