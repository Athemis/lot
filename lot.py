#!/usr/bin/env python

try:
    import libtcodpy as libtcod
except ImportError:
    raise ImportError('----- libtcod.py could not be loaded. -----')
import math
import textwrap
import shelve
try:
    import numpy as np
except ImportError:
    raise ImportError('----- NumPy must be installed. -----')


# actual size of the window
SCREEN_WIDTH = 80
SCREEN_HEIGHT = 50

# size of the map
MAP_WIDTH = 80
MAP_HEIGHT = 43

LEVEL_SCREEN_WIDTH = 40
CHARACTER_SCREEN_WIDTH = 30

# Experience and level-ups
LEVEL_UP_BASE = 200
LEVEL_UP_FACTOR = 150

# Size and number of rooms
ROOM_MAX_SIZE = 10
ROOM_MIN_SIZE = 6
MAX_ROOMS = 30

INVENTORY_WIDTH = 50

HEAL_AMOUNT = 40

LIGHTNING_DAMAGE = 40
LIGHTNING_RANGE = 5

CONFUSE_NUM_TURNS = 10
CONFUSE_RANGE = 8

FIREBALL_DAMAGE = 25
FIREBALL_RADIUS = 3

FOV_ALGO = 0  # default FOV algorithm
FOV_LIGHT_WALLS = True
TORCH_RADIUS = 10
SQUARED_TORCH_RADIUS = TORCH_RADIUS * TORCH_RADIUS
dx = 0.0
dy = 0.0
di = 0.0

fov_recompute = None
fov_noise = None
fov_torchx = 0.0

color_dark_wall = libtcod.Color(40, 40, 40)
color_light_wall = libtcod.Color(60, 60, 60)
color_dark_ground = libtcod.Color(25, 25, 25)
color_light_ground = libtcod.Color(255, 230, 100)

LIMIT_FPS = 20  # 20 frames-per-second limit

# Number of frames to wait after moving/attacking
PLAYER_SPEED = 2
DEFAULT_SPEED = 8
DEFAULT_ATTACK_SPEED = 20

# Sizes and coordinates relevant for the GUI
BAR_WIDTH = 20
PANEL_HEIGHT = 7
PANEL_Y = SCREEN_HEIGHT - PANEL_HEIGHT

MSG_X = BAR_WIDTH + 2
MSG_WIDTH = SCREEN_WIDTH - BAR_WIDTH - 2
MSG_HEIGHT = PANEL_HEIGHT - 1


class Rect:
  # A rectangle on the map
    def __init__(self, x, y, w, h):
        self.x1 = x
        self.y1 = y
        self.x2 = x + w
        self.y2 = y + h

    def center(self):
        center_x = int(round((self.x1 + self.x2) / 2))
        center_y = int(round((self.y1 + self.y2) / 2))
        return (center_x, center_y)

    def intersect(self, other):
        # Returns of this rectangle intersects with another one
        return (self.x1 <= other.x2 and self.x2 >= other.x1 and
                self.y1 <= other.y2 and self.y2 >= other.y1)


class Tile:
  # A tile of the map and its properties

    def __init__(self, blocked, block_sight=None):
        self.blocked = blocked
        self.explored = False

        # By default, a blocked tile also blocks sight
        if block_sight is None:
            block_sight = blocked
        self.block_sight = block_sight


class Object:
  # This is a generic object: player, monster, item, ...
  # It is always represented by a character on screen

    def __init__(self, x, y, char, name, color, blocks=False,
                 always_visible=False, fighter=None, ai=None,
                 item=None, speed=DEFAULT_SPEED):
        self.x = int(x)
        self.y = int(y)
        self.char = char
        self.name = name
        self.color = color
        self.blocks = blocks
        self.always_visible = always_visible
        self.fighter = fighter
        if self.fighter:
            self.fighter.owner = self
        self.ai = ai
        if self.ai:
            self.ai.owner = self
        self.item = item
        if self.item:
            self.item.owner = self
        self.speed = speed
        self.wait = 0

    def distance_to(self, other):
        # Return the distance to another object
        dx = other.x - self.x
        dy = other.y - self.y
        return math.sqrt(dx ** 2 + dy ** 2)

    def distance(self, x, y):
        # Return the distance to some coordinates
        return math.sqrt((x - self.x) ** 2 + (y - self.y) ** 2)

    def move(self, dx, dy):
        # Move by given amount
        try:
            if not is_blocked(self.x + dx, self.y + dy):
                self.x += dx
                self.y += dy
        except:
            self.x = self.x
            self.y = self.y

        self.wait = self.speed

    def move_towards(self, target_x, target_y):
        # vector from this object to the target and distance
        dx = target_x - self.x
        dy = target_y - self.y
        distance = math.sqrt(dx ** 2 + dy ** 2)

        # Normalize it to length 1 (preserving direction), then round it and
        # convert to integer so movement is restricted to the map grid
        dx = int(round(dx / distance))
        dy = int(round(dy / distance))
        self.move(dx, dy)

    def draw(self):
        if (libtcod.map_is_in_fov(fov_map, self.x, self.y) or
           (self.always_visible and map[self.x, self.y].explored)):
            # Set the color and draw the character
            libtcod.console_put_char(con, self.x, self.y,
                                     self.char, libtcod.BKGND_NONE)
            libtcod.console_set_char_foreground(con, self.x,
                                                self.y, self.color)

    def send_to_back(self):
        # Make this object be drawn first, so all other objects appear above
        # if they are in the same tile.
        global objects
        objects.remove(self)
        objects.insert(0, self)

    def clear(self):
        # Erease the character that represents this object
        libtcod.console_put_char(con, self.x, self.y, ' ', libtcod.BKGND_NONE)


class Item:
  # An item that can be picked up and used
    def __init__(self, use_function=None):
        self.use_function = use_function

    def pick_up(self):
        # Add to the player's inventory and remove from the map
        if len(inventory) >= 26:
            message('Your inventory is full, \
                     cannot pick up {}.'.format(self.owner.name), libtcod.red)
        else:
            inventory.append(self.owner)
            objects.remove(self.owner)
            message('You picked up {}!'.format(self.owner.name), libtcod.green)

    def use(self):
        # Just call the use_function if it is defined
        if self.use_function is None:
            message('The {} cannot be used.'.format(self.owner.name))
        else:
            if self.use_function() != 'cancelled':
                inventory.remove(self.owner)  # Destroy after use unless it was
                                              # cancelled for some reason

    def drop(self):
        # Add to the map and remove from the player's inventory
        objects.append(self.owner)
        inventory.remove(self.owner)
        self.owner.x = player.x
        self.owner.y = player.y
        message('You dropped a {}.'.format(self.owner.name), libtcod.yellow)


class Fighter:
    # Combat reated properties and methods (monster, player, NPC)
    def __init__(self, hp, defense, power, xp, death_function=None,
                 attack_speed=DEFAULT_ATTACK_SPEED):
        self.max_hp = hp
        self.hp = hp
        self.defense = defense
        self.power = power
        self.xp = xp
        self.death_function = death_function
        self.attack_speed = attack_speed

    def take_damage(self, damage):
        # Apply damage if possible
        if damage > 0:
            self.hp -= damage
        if self.hp <= 0:
            function = self.death_function
            if function is not None:
                function(self.owner)
                if self.owner != player:  # Yield experience to the player
                    player.fighter.xp += self.xp

    def heal(self, amount):
        # Heal by the given amount, without going over the maximum
        self.hp += amount
        if self.hp > self.max_hp:
            self.hp = self.max_hp

    def attack(self, target):
        # A simple formula for attack damage
        damage = self.power - target.fighter.defense

        if damage > 0:
            # Make the target take some damage
            message('{} attacks {} for {} \
                     hit points.'.format(self.owner.name.capitalize(),
                                         target.name, str(damage)))
            target.fighter.take_damage(damage)
        else:
            message('{} attacks {} but it \
                     has no effect!'.format(self.owner.name.capitalize(),
                                            target.name))

        self.owner.wait = self.attack_speed


class BasicMonster:
    # AI for a basic monster
    def take_turn(self):
        # A basic monster that takes its turn.
        # If you can see it, it can see you
        monster = self.owner
        if libtcod.map_is_in_fov(fov_map, monster.x, monster.y):
            # Move towards player if far away
            if monster.distance_to(player) >= 2:
                monster.move_towards(player.x, player.y)
            # Close enough. Attack if the player is alive
            elif player.fighter.hp > 0:
                monster.fighter.attack(player)


class ConfusedMonster:
    # AI for a temporarily confused monster (reverts to
    # previous AI after a while).
    def __init__(self, old_ai, num_turns=CONFUSE_NUM_TURNS):
        self.old_ai = old_ai
        self.num_turns = num_turns

    def take_turn(self):
        if self.num_turns > 0:  # Still confused
            # Move in a random direction
            self.owner.move(libtcod.random_get_int(0, -1, 1),
                            libtcod.random_get_int(0, -1, 1))
        else:  # Restore the previous AI (this one will be deleted because
               # it's not referenced anymore)
            self.owner.ai = self.old_ai
            message('The {} is no longer confused!'.format(self.owner.name),
                    libtcod.red)


def player_death(player):
    # The game ended!
    global game_state
    message('You died!', libtcod.red)
    game_state = 'dead'

    # For added effect, transform the player into a corpse
    player.char = b'%'
    player.color = libtcod.dark_red


def monster_death(monster):
    # Transform it into a nasty corpse. It does not block, cannot be attacked
    # and does not move

    message('The {} is dead! \
             You gain {} experience.'.format(monster.name.capitalize(),
                                             str(monster.fighter.xp)))
    monster.char = b'%'
    monster.color = libtcod.dark_red
    monster.blocks = False
    monster.fighter = None
    monster.ai = None
    monster.name = 'remains of {}'.format(monster.name)
    monster.send_to_back()


def closest_monster(max_range):
    # Find the closest enemy up to a maximum range and in the player's FOV
    closest_enemy = None
    closest_dist = max_range + 1  # Start with (slightly more than) max. range

    for object in objects:
        if (
            object.fighter and not
            object == player and
            libtcod.map_is_in_fov(fov_map, object.x, object.y)
        ):
            # Calculate the distance between this object and the player
            dist = player.distance_to(object)
            if dist < closest_dist:  # Its closer, so remember it
                closest_enemy = object
                closest_dist = dist
    return closest_enemy


def cast_heal():
    #heal the player
    if player.fighter.hp == player.fighter.max_hp:
        message('You are already at full health.', libtcod.red)
        return 'cancelled'

    message('Your wounds start to feel better!', libtcod.light_violet)
    player.fighter.heal(HEAL_AMOUNT)


def cast_lightning():
    # Find the closest enemy (inside a maximum range) and damage it
    monster = closest_monster(LIGHTNING_RANGE)
    if monster is None:  # No enemy found within maximum range
        message('No enemy is close enough to strike.', libtcod.red)
        return 'cancelled'

    # Zap it!
    message('A lightning bolt strikes the {} with a loud thunder! \
             The damage is {} hit points'.format(monster.name,
                                                 str(LIGHTNING_DAMAGE)),
            libtcod.light_blue)
    monster.fighter.take_damage(LIGHTNING_DAMAGE)


def cast_confuse():
    # Ask the player for a target to confuse
    message('Left-click an enemy to confuse it, \
             or right-click to cancel.', libtcod.light_cyan)
    monster = target_monster(CONFUSE_RANGE)
    if monster is None:
        return 'cancelled'

    # Replace the monster's AI with a "confused" one;
    # after some turns it will restore the old AI
    old_ai = monster.ai
    monster.ai = ConfusedMonster(old_ai)
    monster.ai.owner = monster  # Tell the new component who owns it
    message('The eyes of the {} look vacant, \
             as he starts to stumble around!'.format(monster.name),
            libtcod.light_green)


def cast_fireball():
    # Ask the player for a target tile to throw a fireball at
    message('Left-click a target tile for the fireball, \
             or right-click to cancel.', libtcod.light_cyan)
    (x, y) = target_tile()
    if x is None:
        return 'cancelled'
    message('The fireball explodes, \
             burning everything within {} tiles!'.format(FIREBALL_RADIUS),
            libtcod.orange)

    for obj in objects:  # Damage every fighter in range, including the player
        if obj.distance(x, y) <= FIREBALL_RADIUS and obj.fighter:
            message('The {} gets \
                    burned for {} hit points.'.format(obj.name,
                                                      FIREBALL_DAMAGE),
                    libtcod.orange)
            obj.fighter.take_damage(FIREBALL_DAMAGE)


def target_tile(max_range=None):
  # Return the position of a tile left-clicked in the player's FOV
  # (optionally in a range), or (None, None) if right-clicked
    global key
    global mouse
    while True:
        # Render the screen. This erases the inventory and shows the names of
        # objects under the mouse.
        render_all()
        libtcod.console_flush()
        # Get mouse position and click status
        libtcod.sys_check_for_event((libtcod.EVENT_KEY_PRESS |
                                     libtcod.EVENT_MOUSE), key, mouse)

        (x, y) = (mouse.cx, mouse.cy)
        # print('{}:{}'.format(str(x), str(y)))
        # Accept the taret if the player clicked in FOV and in case a range is
        # specified, if it's in that range
        if (mouse.lbutton_pressed and libtcod.map_is_in_fov(fov_map, x, y) and
           (max_range is None or player.distance(x, y) <= max_range)):
            return (x, y)
        if mouse.rbutton_pressed or key.vk == libtcod.KEY_ESCAPE:
            return (None, None)  # Cancel if right-clicked or Escape is pressed


def target_monster(max_range=None):
    # Returns a clicked monster inside FOV up to a range,
    # or None if right-clicked
    while True:
        (x, y) = target_tile(max_range)
        if x is None:  # Player cancelled
            return None

        # Return the first clicked monster, otherwise continue looping
        for obj in objects:
            if obj.x == x and obj.y == y and obj.fighter and obj != player:
                return obj


def create_room(room):
    global map
    # Go through the tiles in the rectangle and make them passable
    for x in range(room.x1 + 1, room.x2):
        for y in range(room.y1 + 1, room.y2):
            map[x, y].blocked = False
            map[x, y].block_sight = False


def create_h_tunnel(x1, x2, y):
    # Horizontal tunnel
    global map
    for x in range(min(x1, x2), max(x1, x2) + 1):
        map[x, y].blocked = False
        map[x, y].block_sight = False


def create_v_tunnel(y1, y2, x):
    # Vertical tunnel
    global map
    for y in range(min(y1, y2), max(y1, y2) + 1):
        map[x, y].blocked = False
        map[x, y].block_sight = False


def is_blocked(x, y):
    # First test the map tile
    if map[x, y].blocked:
        return true

    # Now check for any blocking object
    for object in objects:
        if object.blocks and object.x == x and object.y == y:
            return True

    return False


def random_choice_index(chances):
# Choose one option from list of chances, returning its index
    # The dice will land on some number between 1 and the sum of the chances
    dice = libtcod.random_get_int(0, 1, sum(chances))

    # Go through all chances, keeping the sum so far
    running_sum = 0
    choice = 0
    for w in chances:
        running_sum += w

        # See if this dice landed in the part that corresponds to this choice
        if dice <= running_sum:
            return choice
        choice += 1


def random_choice(chances_dict):
    # Choose one option from dictionary of chances, returning its key
    chances = chances_dict.values()
    strings = chances_dict.keys()

    return list(strings)[random_choice_index(list(chances))]


def from_dungeon_level(table):
    # Returns a value that depends on level. The table specifies which value
    # occurs after each level, default is 0
    for (value, level) in reversed(table):
        if dungeon_level >= level:
            return value
    return 0


def place_objects(room):
# This is where we decide the chance of each monster or item appearing

    # Maximum number of monsters per room
    max_monsters = from_dungeon_level([[2, 1], [3, 4], [5, 6]])

    # Chance of each monster
    monster_chances = {}
    monster_chances['orc'] = 80
    monster_chances['troll'] = from_dungeon_level([[15, 3], [30, 5], [60, 7]])

    # Maximum number of items per room
    max_items = from_dungeon_level([[1, 1], [2, 4]])

    # Chance of each item (by default they have a chance of 0 at level 1,
    # which then goes up)
    item_chances = {}
    item_chances['heal'] = 35
    item_chances['lightning'] = from_dungeon_level([[25, 4]])
    item_chances['fireball'] = from_dungeon_level([[25, 6]])
    item_chances['confuse'] = from_dungeon_level([[10, 2]])

    # Choose a random number of monsters
    num_monsters = libtcod.random_get_int(0, 0, max_monsters)

    for i in range(num_monsters):
        # Choose random spot for this monster
        x = libtcod.random_get_int(0, room.x1 + 1, room.x2 - 1)
        y = libtcod.random_get_int(0, room.y1 + 1, room.y2 - 1)

        # Only place it if the tile is unblocked
        if not is_blocked(x, y):
            choice = random_choice(monster_chances)
            if choice == 'orc':
                # create an orc
                fighter_component = Fighter(hp=20,
                                            defense=0,
                                            power=4,
                                            xp=35,
                                            death_function=monster_death)
                ai_component = BasicMonster()
                monster = Object(x, y, 'o', 'orc', libtcod.desaturated_green,
                                 blocks=True, fighter=fighter_component,
                                 ai=ai_component)
            elif choice == 'troll':
                # create a troll
                fighter_component = Fighter(hp=30,
                                            defense=2,
                                            power=8,
                                            xp=100,
                                            death_function=monster_death)
                ai_component = BasicMonster()
                monster = Object(x, y, 'T', 'troll', libtcod.darker_green,
                                 blocks=True, fighter=fighter_component,
                                 ai=ai_component)

            objects.append(monster)

            # Choose random number of items
            num_items = libtcod.random_get_int(0, 0, max_items)

            for i in range(num_items):
                # Choose random spot for this item
                x = libtcod.random_get_int(0, room.x1 + 1, room.x2 - 1)
                y = libtcod.random_get_int(0, room.y1 + 1, room.y2 - 1)

                # Only place it if the tile is not blocked
                if not is_blocked(x, y):
                    choice = random_choice(item_chances)
                    if choice == 'heal':
                        # Create a healing potion (70% chance)
                        item_component = Item(use_function=cast_heal)
                        item = Object(x, y, '!', 'healing potion',
                                      libtcod.violet,
                                      item=item_component)
                    elif choice == 'lightning':
                        # Create a lightning bolt scroll (10% chance)
                        item_component = Item(use_function=cast_lightning)
                        item = Object(x, y, '#', 'scroll of lightning bolt',
                                      libtcod.yellow,
                                      item=item_component)
                    elif choice == 'fireball':
                        # Create a fireball scroll (10% chance)
                        item_component = Item(use_function=cast_fireball)
                        item = Object(x, y, '#', 'scroll of fireball',
                                      libtcod.light_orange,
                                      item=item_component)
                    elif choice == 'confuse':
                        # Create a confuse scroll (10% chance)
                        item_component = Item(use_function=cast_confuse)
                        item = Object(x, y, '#', 'scroll of confusion',
                                      libtcod.light_yellow,
                                      item=item_component)

                    objects.append(item)
                    item.send_to_back()
                    item.always_visible = True


def make_map():
    global map, objects, stairs

    # The listof objects with just the player
    objects = [player]

    # Fill the map with unblocked tiles
    map = np.zeros((MAP_WIDTH, MAP_HEIGHT), object)
    for y in range(MAP_HEIGHT):
        for x in range(MAP_WIDTH):
            map[x, y] = Tile(True)

    rooms = []
    num_rooms = 0

    for r in range(MAX_ROOMS):
        # Random width and height
        w = libtcod.random_get_int(0, ROOM_MIN_SIZE, ROOM_MAX_SIZE)
        h = libtcod.random_get_int(0, ROOM_MIN_SIZE, ROOM_MAX_SIZE)
        # Random position without going of the map boundaries
        x = libtcod.random_get_int(0, 0, MAP_WIDTH - w - 1)
        y = libtcod.random_get_int(0, 0, MAP_HEIGHT - h - 1)

        new_room = Rect(x, y, w, h)

        failed = False
        for other_room in rooms:
            if new_room.intersect(other_room):
                failed = True
                break

        if not failed:
            create_room(new_room)
            # add some contents to this room, such as monsters
            place_objects(new_room)
            (new_x, new_y) = new_room.center()

            if num_rooms == 0:
                # if this is the first room, the player starts here
                player.x = new_x
                player.y = new_y
            else:
                # All rooms after the first
                # connect it to the previous room with a tunnel

                #center coordinated of previous room
                (prev_x, prev_y) = rooms[num_rooms - 1].center()

                # Draw a coin (random number that is either 0 or 1)
                if libtcod.random_get_int(0, 0, 1) == 1:
                    # first move horizontally, then vertical
                    create_h_tunnel(prev_x, new_x, prev_y)
                    create_v_tunnel(prev_y, new_y, new_x)
                else:
                    # first move vertically, then horizontally
                    create_v_tunnel(prev_y, new_y, prev_x)
                    create_h_tunnel(prev_x, new_x, new_y)

            # Finally, append the new room to the list
            rooms.append(new_room)
            num_rooms += 1

    # Create stairs at the center of the last room
    stairs = Object(new_x, new_y, '<', 'stairs', libtcod.white,
                    always_visible=True)
    objects.append(stairs)


def next_level():
    # Advance to the next level
    global dungeon_level

    message('You take a moment to rest and recover your strength.',
            libtcod.light_violet)
    # Heal the player by 50 %
    player.fighter.heal(int(round(player.fighter.max_hp / 2)))

    message('After a rare moment of peace, you descend \
            deeper into the heart of the dungeon...', libtcod.red)
    dungeon_level += 1
    make_map()
    initialize_fov()


def render_all():

    global fov_map, color_dark_wall, color_light_wall
    global color_dark_ground, color_light_ground
    global fov_recompute, fov_torchx

    if fov_recompute:
        #recompute FOV if needed (the player moved or something)
        fov_recompute = False
        libtcod.map_compute_fov(fov_map, player.x, player.y, TORCH_RADIUS,
                                FOV_LIGHT_WALLS, FOV_ALGO)

    #torch flickers (using noise generator)
    fov_torchx += 0.2
    tdx = [fov_torchx + 20.0]
    dx = libtcod.noise_get(fov_noise, tdx) * 1.5
    tdx[0] += 30.0
    dy = libtcod.noise_get(fov_noise, tdx) * 1.5
    di = 0.2 * libtcod.noise_get(fov_noise, [fov_torchx])

    # Iterate through rendering queue
    for y in range(MAP_HEIGHT):
        for x in range(MAP_WIDTH):
            visible = libtcod.map_is_in_fov(fov_map, x, y)
            wall = map[x, y].block_sight  # check if tile is a wall
            if not visible:
                # if it's not visible right now, the player can only
                # see it if it's explored
                if map[x, y].explored:
                    # It's out of the player's FOV
                    if wall:
                        libtcod.console_set_char_background(con, x, y,
                                                            color_dark_wall,
                                                            libtcod.BKGND_SET)
                    else:
                        libtcod.console_set_char_background(con, x, y,
                                                            color_dark_ground,
                                                            libtcod.BKGND_SET)
            else:
            # It's visible
                if wall:
                    base = color_dark_wall
                    light = color_light_wall
                else:
                    base = color_dark_ground
                    light = color_light_ground

                #Let the torch actually flicker
                r = float(x - player.x + dx) * (x - player.x + dx) + \
                         (y - player.y + dy) * (y - player.y + dy)
                if r < SQUARED_TORCH_RADIUS:
                    l = (SQUARED_TORCH_RADIUS - r) / SQUARED_TORCH_RADIUS + di
                    if l < 0.0:
                        l = 0.0
                    elif l > 1.0:
                        l = 1.0
                    # alter base colors to simulate flickering torch
                    base = libtcod.color_lerp(base, light, l)
                # actually draw the visible tile
                libtcod.console_set_char_background(con, x, y, base,
                                                    libtcod.BKGND_SET)
                #since it's visible, it's explored
                map[x, y].explored = True

    # Draw all objects in the list
    for object in objects:
        if object != player:
            object.draw()
    player.draw()

    # Blit the contents of con to the root console
    libtcod.console_blit(con, 0, 0, MAP_WIDTH, MAP_HEIGHT, 0, 0, 0)

    # Prepare to render the GUI panel
    libtcod.console_set_default_background(panel, libtcod.black)
    libtcod.console_clear(panel)

    # Print the game messages
    y = 1
    for (line, color) in game_msgs:
        libtcod.console_set_default_foreground(panel, color)
        libtcod.console_set_alignment(panel, libtcod.LEFT)
        libtcod.console_print(panel, MSG_X, y, line)
        y += 1

    # Show the player's stats
    render_bar(1, 1, BAR_WIDTH, 'HP', player.fighter.hp, player.fighter.max_hp,
               libtcod.light_red, libtcod.darker_red)

    libtcod.console_set_alignment(panel, libtcod.LEFT)
    libtcod.console_print(panel, 1, 3,
                          'Dungeon level {}'.format(str(dungeon_level)))

    # Display names of objects under the mouse
    libtcod.console_set_default_foreground(panel, libtcod.light_grey)
    libtcod.console_print(panel, 1, 0, get_names_under_mouse())

    # Blit the contents of "panel" to the root console
    libtcod.console_blit(panel, 0, 0, SCREEN_WIDTH, PANEL_HEIGHT, 0, 0,
                         PANEL_Y)


def menu(header, options, width):
    global key
    global mouse

    if len(options) > 26:
        raise ValueError('Cannot have a menu with more than 26 options!')
    # Calculate total height for the header (after auto-wrap)
    # and one line per option
    header_height = libtcod.console_get_height_rect(con, 0, 0, width,
                                                    SCREEN_HEIGHT, header)
    if header == '':
        header_height = 0
    height = len(options) + header_height

    # Create an off-screen console that represents the menu's window
    window = libtcod.console_new(width, height)

    # Print the header, with auto-wrap
    libtcod.console_set_default_foreground(window, libtcod.white)
    libtcod.console_set_alignment(window, libtcod.LEFT)
    libtcod.console_set_default_background(window, libtcod.BKGND_NONE)
    libtcod.console_print_rect(window, 0, 0, width, height, header)

    # Print all the options
    y = header_height
    letter_index = ord('a')
    for option_text in options:
        text = '({}) {}'.format(chr(letter_index), option_text)
        libtcod.console_print(window, 0, y, text)
        y += 1
        letter_index += 1

    # Blit the contents of "window" to the root console
    x = int(round(SCREEN_WIDTH / 2 - width / 2))
    y = int(round(SCREEN_HEIGHT / 2 - height / 2))
    libtcod.console_blit(window, 0, 0, width, height, 0, x, y, 1.0, 0.7)

    # Present the root console to the player and wait for a key-press
    libtcod.console_flush()

    libtcod.sys_wait_for_event(libtcod.EVENT_KEY_PRESS, key, mouse, False)

    if key.vk == libtcod.KEY_ENTER and key.lalt:
    #(special case) Alt+Enter: toggle fullscreen
        libtcod.console_set_fullscreen(not libtcod.console_is_fullscreen())

    # Convert the ASCII code to an index; if it corresponds to an
    # option, return it
    index = key.c - ord('a')
    if index >= 0 and index < len(options):
        return index
    return None


def msgbox(text, width=50):
    menu(text, [], width)  # Use menu() as a sort of "message box"


def inventory_menu(header):
    # Show a menu with each item of the inventory as an option
    if len(inventory) == 0:
        options = ['Inventory is empty.']
    else:
        options = [item.name for item in inventory]

    index = menu(header, options, INVENTORY_WIDTH)

    # If an item was chosen, return it
    if index is None or len(inventory) == 0:
        return None
    return inventory[index].item


def render_bar(x, y, total_width, name, value, maximum, bar_color, back_color):
    # Render a bar (HP, experience, etc). First calculate the width of the bar
    bar_width = int(float(value) / maximum * total_width)

    # Render the background first
    libtcod.console_set_default_background(panel, back_color)
    libtcod.console_rect(panel, x, y, total_width, 1, False, libtcod.BKGND_SET)

    # Now render the bar on top
    libtcod.console_set_default_background(panel, bar_color)
    if bar_width > 0:
        libtcod.console_rect(panel, x, y, bar_width, 1, False,
                             libtcod.BKGND_SET)

    # Add centered text with values
    libtcod.console_set_default_foreground(panel, libtcod.white)
    libtcod.console_set_alignment(panel, libtcod.CENTER)
    bar_text = '{}: {}/{}'. format(name, str(value), str(maximum))
    libtcod.console_print(panel, int(x + total_width / 2), y, bar_text)


def message(new_msg, color=libtcod.white):
    # Split the message if necesary, among multiple lines
    new_msg_lines = textwrap.wrap(new_msg, MSG_WIDTH)

    for line in new_msg_lines:
        # if the buffer is full, remove first line to make room for the new one
        if len(game_msgs) == MSG_HEIGHT:
            del game_msgs[0]

        # Add the new line as a tuple, with the text and coloe
        game_msgs.append((line, color))


def get_names_under_mouse():
    # Return a string with the names of all objects under the mouse
    global key
    global mouse

    libtcod.sys_check_for_event(libtcod.EVENT_MOUSE, key, mouse)

    (x, y) = (mouse.cx, mouse.cy)

    # Create a list with the names of all objects at the mouse's
    # coordinates and in FOV
    names = [obj.name for obj in objects
             if (obj.x == x and
                 obj.y == y and
                 libtcod.map_is_in_fov(fov_map, obj.x, obj.y))]

    names = ', '.join(names)  # join the names, separated by commas
    return names.capitalize()


def handle_keys():
    global fov_recompute

    global key
    global mouse

    libtcod.sys_check_for_event(libtcod.EVENT_KEY_PRESS, key, mouse)

    if key.vk == libtcod.KEY_ENTER and key.lalt:
        # Alt+Enter: Fullscreen
        libtcod.console_set_fullscreen(not libtcod.console_is_fullscreen())
        return
    elif key.vk == libtcod.KEY_ESCAPE:
        return 'exit'  # exit game

    if game_state == 'playing':
        if player.wait > 0:  # Don't take a turn yet if still waiting
            player.wait -= 1
            return
        if libtcod.console_is_key_pressed(libtcod.KEY_UP):
            player_move_or_attack(0, -1)
            fov_recompute = True
        elif libtcod.console_is_key_pressed(libtcod.KEY_DOWN):
            player_move_or_attack(0, 1)
            fov_recompute = True
        elif libtcod.console_is_key_pressed(libtcod.KEY_LEFT):
            player_move_or_attack(-1, 0)
            fov_recompute = True
        elif libtcod.console_is_key_pressed(libtcod.KEY_RIGHT):
            player_move_or_attack(1, 0)
            fov_recompute = True
        # Diagonal movement using the numpad keys
        elif libtcod.console_is_key_pressed(libtcod.KEY_KP7):
            player_move_or_attack(-1, -1)
            fov_recompute = True
        elif libtcod.console_is_key_pressed(libtcod.KEY_KP9):
            player_move_or_attack(1, -1)
            fov_recompute = True
        elif libtcod.console_is_key_pressed(libtcod.KEY_KP1):
            player_move_or_attack(-1, 1)
            fov_recompute = True
        elif libtcod.console_is_key_pressed(libtcod.KEY_KP3):
            player_move_or_attack(1, 1)
            fov_recompute = True
        else:
            key_char = chr(key.c)

            if key_char == 'g':
                # Pick up an item
                for object in objects:  # Look for an item in the player's tile
                    if (
                        object.x == player.x and object.y == player.y and
                        object.item
                    ):
                            object.item.pick_up()
                            break
            if key_char == 'i':
                # Show the inventory
                chosen_item = inventory_menu('Press the key next to an \
                                              item to use it, or any other \
                                              to cancel.\n')
                if chosen_item is not None:
                    chosen_item.use()
            if key_char == 'd':
                # Show the inventory; if an item is selected, drop it
                chosen_item = inventory_menu('Press the key next to an \
                                              item to drop it, or any other \
                                              to cancel.\n')
                if chosen_item is not None:
                    chosen_item.drop()
            if key_char == '<':
                # Go down stairs, if the player is on them
                if stairs.x == player.x and stairs.y == player.y:
                    next_level()
            if key_char == 'c':
                # Show character information
                level_up_xp = LEVEL_UP_BASE + player.level * LEVEL_UP_FACTOR
                msgbox('Character Information\n\nLevel: {}\n\
                        Experience: \{}\nExperience to level up: {}\n\n\
                        Maximum HP: {}\nAttack: {}\n\
                        Defense: {}'.format(str(player.level),
                                            str(player.fighter.xp),
                                            str(level_up_xp),
                                            str(player.fighter.max_hp),
                                            str(player.fighter.power),
                                            str(player.fighter.defense)),
                       CHARACTER_SCREEN_WIDTH)

            return 'didnt-take-turn'


def player_move_or_attack(dx, dy):
    global fov_recompute

    # The coordinated the player is moving to
    x = player.x + dx
    y = player.y + dy

    # Try to find an attackable object there
    target = None
    for object in objects:
        if object.fighter and object.x == x and object.y == y:
            target = object
            break

    # Attack if target found, move otherwise
    if target is not None:
        player.fighter.attack(target)
    else:
        player.move(dx, dy)
        fov_recompute = True


def check_level_up():
    # See if the player's experience is enough to level-up
    level_up_xp = LEVEL_UP_BASE + player.level * LEVEL_UP_FACTOR
    if player.fighter.xp >= level_up_xp:
        # It is! Level up
        player.level += 1
        player.fighter.xp -= level_up_xp
        message('Your battle skills grow stronger! \
                 You reached level {}!'.format(str(player.level)),
                libtcod.yellow)

        choice = None
        while choice is None:  # Keep asking until a choice is made
            choice = menu('Level up! Choose a stat to raise:\n',
                          ['Constitution \
                           (+20 HP, from {})'.format(str(player.fighter.hp)),
                           'Strenght (+1 attack, \
                           from {})'.format(str(player.fighter.power)),
                           'Agility (+1 defense, \
                           from {})'.format(str(player.fighter.defense))],
                          LEVEL_SCREEN_WIDTH)

        if choice == 0:
            player.fighter.max_hp += 20
            player.fighter.hp += 20
        elif choice == 1:
            player.fighter.power += 1
        elif choice == 2:
            player.fighter.defense += 1


def initialize_fov():
    global fov_recompute, fov_map, fov_noise
    fov_recompute = True

    libtcod.console_clear(con)  # Unexplored areas start black (which
                                # is the default background color)

    #create the FOV map, according to the generated map
    fov_noise = libtcod.noise_new(1, 1.0, 1.0)
    fov_map = libtcod.map_new(MAP_WIDTH, MAP_HEIGHT)
    for y in range(MAP_HEIGHT):
        for x in range(MAP_WIDTH):
            libtcod.map_set_properties(fov_map, x, y,
                                       not map[x, y].block_sight,
                                       not map[x, y].blocked)


def new_game():
    global player, inventory, game_msgs, game_state, key, mouse, dungeon_level

    # Create object representing the player
    fighter_component = Fighter(hp=100, defense=1, power=4, xp=0,
                                death_function=player_death)
    player = Object(0, 0, b'@', 'player', libtcod.white, blocks=True,
                    fighter=fighter_component, speed=PLAYER_SPEED)

    player.level = 1
    # Generate map
    dungeon_level = 1
    make_map()
    initialize_fov()

    game_state = 'playing'
    inventory = []

    # Create the list of game messages and their colors, starts empty
    game_msgs = []

    # a warm welcoming message!
    message('Welcome stranger! Prepare to perish in the \
             Tombs of the Ancient Kings.', libtcod.red)


def play_game():
    player_action = None

    while not libtcod.console_is_window_closed():
        # Render the screen
        render_all()

        libtcod.console_flush()
        check_level_up()

        # Erease all objects at their old locations, befor they move
        for object in objects:
            object.clear()

        # Handle keys and exit if needed
        player_action = handle_keys()
        if player_action == 'exit':
            save_game()  # Save the current game before exit
            break

        # Let the monsters take their turn
        if game_state == 'playing':
            for object in objects:
                if object.ai:
                    # Don't take a turn yet if still waiting
                    if object.wait > 0:
                        object.wait -= 1
                    else:
                        object.ai.take_turn()


def save_game():
    # Open a new emtpy shelve (possibly overwriting an old one)
    # to write the game data
    file = shelve.open('savegame', 'n')
    file['map'] = map
    file['objects'] = objects
    # Index of player in objects list
    file['player_index'] = objects.index(player)
    file['inventory'] = inventory
    file['game_msgs'] = game_msgs
    file['game_state'] = game_state
    file['stairs_index'] = objects.index(stairs)
    file['dungeon_level'] = dungeon_level
    file.close()


def load_game():
    # Open the previously saved shelve and load the game data
    global map, objects, player, inventory, game_msgs
    global game_state, stairs, dungeon_level

    file = shelve.open('savegame', 'r')
    map = file['map']
    objects = file['objects']
    # Get the index of the player in objects list and access it
    player = objects[file['player_index']]
    inventory = file['inventory']
    game_msgs = file['game_msgs']
    game_state = file['game_state']
    stairs = objects[file['stairs_index']]
    dungeon_level = file['dungeon_level']
    file.close()

    initialize_fov()


def main_menu():
    img = libtcod.image_load(b'img/backgrounds/menu_background.png')

    while not libtcod.console_is_window_closed():
        # Show the background image at twice the regular console resolution
        libtcod.image_blit_2x(img, 0, 0, 0)

        # Show the game's title
        libtcod.console_set_default_foreground(0, libtcod.light_yellow)
        libtcod.console_set_alignment(0, libtcod.CENTER)
        libtcod.console_print(0, int(round(SCREEN_WIDTH / 2)),
                              int(round(SCREEN_HEIGHT / 2 - 4)),
                              'THE LEGEND OF THARSA')
        libtcod.console_print(0, int(round(SCREEN_WIDTH / 2)),
                              int(round(SCREEN_HEIGHT - 2)),
                              'By Athemis')

        # Show the options and wait for the player's choice
        choice = menu('', ['Play a new game', 'Continue last game', 'Quit'],
                      24)

        if choice == 0:  # New game
            new_game()
            play_game()
        elif choice == 1:  # Load last game
            try:
                load_game()
            except:
                msgbox('\n No saved game to load. \n', 24)
                continue
            play_game()
        elif choice == 2:  # Quit
            break


##############################
# Initialization & Main Loop
##############################

libtcod.console_set_custom_font(b'img/fonts/arial10x10.png',
                                (libtcod.FONT_TYPE_GREYSCALE |
                                 libtcod.FONT_LAYOUT_TCOD))
libtcod.console_init_root(SCREEN_WIDTH, SCREEN_HEIGHT,
                          b'LoT - The Legend of Tharsa', False)
libtcod.sys_set_fps(LIMIT_FPS)

con = libtcod.console_new(MAP_WIDTH, MAP_HEIGHT)
panel = libtcod.console_new(SCREEN_WIDTH, PANEL_HEIGHT)

key = libtcod.Key()
mouse = libtcod.Mouse()

main_menu()
