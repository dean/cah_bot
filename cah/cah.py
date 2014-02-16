import random
import re
import urllib2

from collections import defaultdict

from hamper.interfaces import ChatCommandPlugin, Command
from hamper.utils import ude, uen

from sqlalchemy import Column, Integer, String, Boolean, desc
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
                 '!winner <answer #> - Chooses a winner for a given prompt.'
                 '!mystatus - Shows information about yourself.')

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
    answers = defaultdict(list)
    kick_votes = defaultdict(list)

    already_in = "{0}, you are already a part of the game!"
    not_in = "{0}, you are not a part of the game!"

    def setup(self, loader):
        super(CardsAgainstHumanity, self).setup(loader)
        self.db = loader.db
        SQLAlchemyBase.metadata.create_all(self.db.engine)

        flush = False
        ct = self.db.session.query(CardTable)

        # Update db if it's empty.
        if ct.count() == 0 or flush:
            self.flush_db()

        whites = ct.filter_by(color="white").all()
        blacks = ct.filter_by(color="black").all()
        self.whites = [uen(white.desc) for white in whites]
        self.blacks = [uen(black.desc) for black in blacks]

        random.seed()

        random.shuffle(self.whites) # Erry' day I'm shufflin'!
        random.shuffle(self.blacks)

    def remove_player(self, bot, comm, player):
        # Return cards to discard
        self.white_discard += self.players[player]

        # Remove player
        del(self.players[player])
        if player in self.kick_votes:
            del(self.kick_votes[player])

        if player in self.player_queue:
            self.player_queue.remove(player)

        while player in self.dealer_queue:
            self.dealer_queue.remove(player)

        if self.state == "play":
            if player in self.avail_players:
                if player in self.answers:
                    self.white_discard += self.answers[player]
                    del(self.answers[player])
                self.avail_players.remove(player)
            elif player == self.dealer:
                bot.reply(comm, "Game restarting... dealer left.")
                self.reset(bot, comm)

            if len(self.players) < 3:
                bot.reply(comm, "There are less than 3 players playing "
                            "now. Waiting for more players...")
                self.reset(bot, comm)

        elif self.state == "winner":
            if player == self.dealer:
                bot.reply(comm, "Game restarting... Dealer left.")
                self.reset(bot, comm)

        bot.reply(comm, self.current_players())



    def give_point(self, user):
        player_str = self.get_player_str()
        winner = self.db.session.query(CAHTable).filter_by(game=player_str,
                                                      user=user).first()
        try:
            winner.score += 1
        except AttributeError:
            self.db.session.add(CAHTable(user, player_str, score=1))

        for player in self.players:
            if not self.db.session.query(CAHTable).filter_by(game=player_str, user=player).first():
                self.db.session.add(CAHTable(user=player, game=player_str))

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
        self.kick_votes.clear()

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

    def prep_play(self, bot, comm):
        self.state = "play"

        if not self.dealer_queue:
            self.dealer_queue += self.players

        self.dealer = self.dealer_queue.pop(0)
        self.prompt = self.blacks.pop(0)
        self.avail_players = [p for p in self.players if p != self.dealer]

        bot.reply(comm, "[*] {0} reads: {1}".format(self.dealer, self.prompt))
        bot.reply(comm, "[*] Type: \"!play <card #>\" to fill blanks. Multiple "
                        "cards are played with \"!play <card #> <card #>\".")

        for p in self.players:
            self.deal(p)

        # Show current hand to players
        for p in self.avail_players:
            self.show_hand(bot, p)

    def colorize(self, txt):
        if txt == '_' * 10:
            # Returns the light cyan color code
            return "\x0311" + txt + "\x03"
        # Returns the light green color code
        return "\x0309" + txt + "\x03"

    def get_player_str(self):
        return ' '.join(sorted(self.players.keys(), key=lambda x: x))

    def show_top_scores(self, bot, comm, current_players=True):
        if current_players:
            player_str = self.get_player_str()
            print player_str
            top = self.db.session.query(CAHTable).filter_by(game=player_str).order_by(
                    CAHTable.score.desc()).all()
        else:
            top = self.db.session.query(CAHTable).order_by(
                        CAHTable.score.desc().all())

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
        self.db.session.query(CardTable).filter_by(official=True).delete()

        url = "http://web.engr.oregonstate.edu/~johnsdea/"

        whites_txt = urllib2.urlopen(url + "whites.txt").read().split("\n")
        blacks_txt = urllib2.urlopen(url + "blacks.txt").read().split("\n")
        new_whites = map(self.format_white, whites_txt)
        for white in new_whites:
            if white:
                self.db.session.add(CardTable(ude(white), "white"))
        new_blacks = map(self.init_black, blacks_txt)
        for black in new_blacks:
            if black:
                self.db.session.add(CardTable(ude(black), "black"))

        self.db.session.commit()

    def format_white(self, card):
        card = card.strip("\n")
        if card:
            if card.endswith("."):
                card = card[:-1]
            return card

    def init_black(self, card):
        card = card.strip("\n")
        if card:
            if "__________" not in card:
                card += " __________."
            return ''.join(map(self.colorize, re.split("(" + '_'*10 + ")", card)))

    def format_black(self, card):
        for x in xrange(card.count("__________")):
            card = card.replace("__________", "{" + str(x) + "}", 1)
        return card

    def show_hand(self, bot, name):
        print "Showing hand for: " + name
        cards = '. '.join((str(x + 1) + ": " + self.players[name][x]
                            for x in xrange(len(self.players[name]))))

        bot.notice(name, "Your hand is: [" + cards + "]")

    def show_answers(self, bot, comm):
        for i, player in enumerate(self.avail_players):
            prompt = self.format_black(self.prompt)
            cards = prompt.format(*self.answers[player])
            text = ("[*] [Answer #{0}]: {1}".format(i + 1, cards))
            bot.reply(comm, text)

        bot.reply(comm, "{0}, please choose a winner with "
                    "\"!winner <answer #>\".".format(self.dealer))


    def current_players(self):
        players = ', '.join(p for p in self.players) + '.'
        return "[*] Current players: " + players

    def queued_players(self):
        players = ', '.join(p for p in self.player_queue) + '.'
        return "[*] Queued Players: " + players

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

            bot.reply(comm, "{0} has left the game!".format(user))
            self.plugin.remove_player(bot, comm, user)

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

            try:
                indices = map(int, groups[0].split(" "))
            except:
                return bot.reply(comm, "{0}, you didn't provide hand index(s) for cards!"
                            .format(user))

            if len(indices) != self.plugin.prompt.count("__________"):
                return ("{0}, you didn't provide the correct amount"
                            "of cards!".format(user))

            if user in self.plugin.answers:
                self.plugin.players[user] += self.plugin.answers[user]
                del(self.plugin.answers[user])

            self.plugin.answers[user] = [self.plugin.players[user][i - 1]
                                    for i in indices]

            # Don't change index of cards that are being removed..
            for index in reversed(sorted(indices, key=lambda x: x)):
                self.plugin.players[user].pop(index - 1)


            if len(self.plugin.answers) == len(self.plugin.avail_players):
                bot.reply(comm, "[*] All players have turned in their cards.")
                random.shuffle(self.plugin.avail_players)
                self.plugin.show_answers(bot, comm)
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
            if winner_ind not in xrange(1, len(self.plugin.answers) + 1):
                return bot.reply(comm, "{0}, that answer doesn't exist!"
                            .format(user))

            winner = self.plugin.avail_players[winner_ind - 1]
            bot.reply(comm, "{0}, you won this round! Congrats!".format(winner))

            self.plugin.give_point(winner)
            self.plugin.show_top_scores(bot, comm)
            self.plugin.reset(bot, comm)

    class MyStatus(Command):
        name = 'mystatus'
        regex = r'^mystatus'

        short_desc = '!mystatus - Shows information about yourself.'
        long_desc = 'Shows information about yourself regarding the game.'

        def command(self, bot, comm, groups):
            print "intercepted mystatus command!"
            user = comm['user']
            msg = ["{0}", "Score: {0}", "Playing: {0}", "Dealer: {0}",
                    "Hand: [{0}]"]

            score = 0
            player = self.plugin.db.session.query(CAHTable).filter_by(user=user
                        ).first()
            if player:
                score = player.score

            playing = "Yes" if user in self.plugin.players else "No"
            dealer = "Yes" if user == self.plugin.dealer else "No"
            hand = "None"
            if user in self.plugin.players:
                hand = '. '.join((str(x + 1) + ": " + self.plugin.players[user][x]
                    for x in xrange(len(self.plugin.players[user]))))

            # Since we can't print new lines...
            msgs = zip(msg, [user, score, playing, dealer, hand])
            for msg, value in msgs:
                bot.notice(user, msg.format(value))

    class Players(Command):
        name = 'players'
        regex = r'^players'

        short_desc = '!players - Shows the current players.'
        long_desc = 'Shows players playing, and in the queue.'

        def command(self, bot, comm, groups):
            print "intercepted players command"

            bot.reply(comm, self.plugin.current_players())
            bot.reply(comm, self.plugin.queued_players())

    class Kick(Command):
        name = 'kick'
        regex = r'^kick (.+)'

        short_desc = '!kick <player_name> Cast a vote to kick a player.'
        long_desc = ('Vote to kick a player. If 70% or more of the current '
                     'players vote to kick a player, they should be kicked.')

        def command(self, bot, comm, groups):
            print "intercepted kick command"
            user = comm['user']
            target = groups[0]
            print target

            if not self.plugin.players.get(target):
                return bot.reply(comm, "Player '{0}' doesn't exist...".format(target))
            elif user in self.plugin.kick_votes[target]:
                return bot.reply(comm, "You already voted to kick this player!")
            elif user == target:
                return bot.reply(comm, "You can't kick yourself!")

            self.plugin.kick_votes[target].append(user)
            num_votes = len(self.plugin.kick_votes[target])
            num_voters = len(self.plugin.players) - 1

            # if 70% or more of voting players want to kick a player, they are
            # kicked
            if ((num_votes/float(num_voters)) * 100 ) > 70:
                self.plugin.remove_player(bot, comm, target)
                bot.reply(comm, "{0} has been kicked from the game!".format(target))

    class Hand(Command):
        name = 'hand'
        regex = r'^hand'

        short_desc = '!hand - Shows your current hand.'

        def command(self, bot, comm, groups):
            print "intercepted hand command"
            self.plugin.show_hand(bot, comm['user'])

    class AddCard(Command):
        name = 'addcard'
        regex = r'^addcard \"(.+)\" \"?(.+)\"?$'

        short_desc = '!addcard - Adds a card to the deck.'
        long_desc = ('!addcard "Description/Text of card" "color".'
                     'To indicate the blanks for a black card, use one "_".')

        def command(self, bot, comm, groups):
            print "intercepted addcard command"

            desc = groups[0]
            color = groups[1]

            if color not in ['white', 'black']:
                return bot.reply(comm, "That color card doesn't exist!")

            elif color == 'black':
                underscore_re = re.compile('(_+)+')
                formatted, num_replacements = underscore_re.subn('_'*10, desc)

                if num_replacements == 0 or num_replacements > 3:
                    return bot.reply(comm, "You provided too few or many blanks!")

                desc = ude(self.plugin.init_black(formatted))
                self.plugin.black_discard.append(desc)

            elif color == 'white':
                desc = ude(self.plugin.format_white(desc))
                self.plugin.white_discard.append(desc)

            new_card = CardTable(desc=desc, color=color, official=False)
            self.plugin.db.session.add(new_card)
            self.plugin.db.session.commit()

            return bot.reply(comm, 'Card: {0} Color: {1} added to db!'.format(
                        desc, color))

    class Poke(Command):
        name = 'poke'
        regex = r'^poke (.+)'

        short_desc = '!poke - Pokes a player with a short reminder.'

        def command(self, bot, comm, groups):
            print "intercepted poke command"

            # Get rid of trailing whitespace.
            target = groups[0].strip()

            if target not in self.plugin.players:
                return bot.reply(comm, 'That player is not playing right now!')
            elif target == comm['user']:
                return bot.reply(comm, 'Why are you poking yourself?')
            if target == self.plugin.dealer:
                if self.plugin.state != 'winner':
                    return bot.reply(comm, 'The dealer doesn\'t need to do '
                                     'anything right now.')
                self.plugin.show_answers(bot, comm)
            else:
                if self.plugin.state == 'play':
                    if target not in self.plugin.answers:
                        bot.notice(target, 'Please play a card.')
                        self.plugin.show_hand(bot, target)
                    else:
                        return bot.reply(comm, '{0} has already played their '
                                         'cards!'.format(target))
                else:
                    return bot.reply(comm, 'Players do not need to do anything'
                                     ' right now.')



class CardTable(SQLAlchemyBase):
    """
    This is only for persistant storage of all cards. More can also be
    added through commands in this manner.
    """

    __tablename__ = 'cah_cards'

    id = Column(Integer, primary_key=True)
    desc = Column(String)
    color = Column(String)
    official = Column(Boolean)

    def __init__(self, desc, color, official=True):
        self.desc = desc
        self.color = color
        self.official = official

    def __repr__(self):
        print self.desc
        return self.desc


class CAHTable(SQLAlchemyBase):
    """
    For storing scores on a per player per game basis.
    """

    __tablename__ = 'cah'

    id = Column(Integer, primary_key=True)
    game = Column(String)
    user = Column(String)
    score = Column(Integer)

    def __init__(self, user, game, score=0):
        self.user = user
        self.game = game
        self.score = score

    def __repr__(self):
        return "%s: %d" % self.user, self.score


cah = CardsAgainstHumanity()
