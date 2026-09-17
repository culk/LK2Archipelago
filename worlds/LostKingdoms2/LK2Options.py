from __future__ import annotations

from dataclasses import dataclass
from Options import Choice, Option, PerGameCommonOptions, Range, DeathLink, Toggle, Visibility

class WinConditionOption(Choice):
    """Choose the win condition.
    Warning: Emperor win condition may be bugged right now.
    Baseline: 175 locations, 175 items"""
    display_name = "Win Condition"
    option_defeat_god_of_harmony = 0
    option_defeat_emperor = 1
    option_collect_red_fairies = 2
    #option_collect_all_cards = 3
    default = 0

class CollectRedFariesAmount(Range):
    """How many red fairies you need to goal.
    Only relevant if your goal is collecting red fairies."""
    display_name = "Collect Red Fairies Amount"
    range_start = 1
    range_end = 97
    default = 50

class FairysanityConditionOption(Toggle):
    """Choose whether Red Fairies are added to the pool.
    +100 locations, +100 items."""
    display_name = "Fairysanity"
    default = 1

class ShopsanityConditionOption(Toggle):
    """Choose whether cards in the shop becomes AP items."""
    visibility = Visibility.none
    display_name = "Shopsanity"
    default = 0

class CombosanityConditionOption(Toggle):
    """Choose whether to add combos as locations.
    +40 locations."""
    display_name = "Combosanity"
    default = 0

class EnemysanityConditionOption(Choice):
    """Choose whether to make enemy kills into locations. Light means one check per "species" of enemy.
    While standard enemysanity is one check per instance of an enemy.
    Plus means that enemies in the Proving Grounds will be included, otherwise they are excluded.
    Be warned that some spawn triggers in this game are very unintuitive, hidden, and
    once a level is beaten it will have new enemy spawn triggers. Please report any issue you encounter.
    Light: ~113 locations
    Light Plus: ~203 locations
    Enemysanity: ~552 locations
    Enemysanity Plus: ~955 locations"""
    display_name = "Enemysanity"
    option_disabled = 0
    option_enemysanity_light = 1
    option_enemysanity_light_plus = 2
    option_enemysanity = 3
    option_enemysanity_plus = 4
    default = 0

class BreaksanityOption(Toggle):
    """All breakable objects in levels are checks(for example, the crates in Nobleman's Residence)
    +268 locations"""
    display_name = "Breaksanity"
    default = 0

class ProgressiveLevelingOption(Toggle):
    """Choose whether to have character levels as a progressive item. You will no longer be able to level up normally.
    +19 items"""
    display_name = "Progressive Leveling"
    default = 0

class ProgressiveAttributeProficienciesOption(Toggle):
    """Choose whether to have character levels as a progressive item. You will no longer be able to level up normally.
    +34 items"""
    display_name = "Progressive Leveling"
    default = 0

class OpenWorldConditionOption(Toggle):
    """Choose whether all levels are unlocked from the start."""
    visibility = Visibility.none
    display_name = "Open World"
    default = 0

class ExcludeSacredBattleArenaChecksOption(Toggle):
    """By enabling, prevents the checks in the sacred battle arenas from being progressive.(There are still checks)"""
    display_name = "Exclude Sacred Battle Checks"
    default = 0

class LevelUnlocksAsItems(Toggle):
    """Whether to add level unlocks to the pool.
    Instead of unlocking a level after beating a level, you must find the level unlocks as AP items
    Takes precedence over Level randomization.
    Experimental; there may be serious bugs, so play at your own risk, and report any issues."""
    display_name = "Level Unlocks as Items"
    default = 0

class RandomizeStartingDeck(Choice):
    """
    Choose whether to randomize your starting deck.
    Off = Vanilla, no randomization of the starting deck.
    Weighted Random = Randomized, with a much higher chance to get cards with low magic costs. (No key cards)
    Fully Random = Randomized; every card is equally likely to appear in your starting deck. (No key cards)
    """
    display_name = "Randomize Starting Deck"
    option_off = 0
    option_weighted_random = 1
    option_fully_random = 2
    default = 1

class RandomizeShopContents(Choice):
    """
    Choose whether to randomize what cards appear in the shops.
    Off = Vanilla, no randomization of the shops' contents.
    Weighted Random = Randomized. Early shops are more likely to have low magic cost cards, later shops are more likely to have higher cost cards. (No key cards)
    Fully Random = Randomized; every card is equally likely to appear in the shop. (No key cards)
    """
    display_name = "Randomize Shop Contents"
    option_off = 0
    option_weighted_random = 1
    option_fully_random = 2
    default = 1

class RandomizeBonusDraws(Choice):
    """
    Choose whether to randomize the contents of the bonus draws at the end of each level.
    Off = Vanilla, no randomization of the bonus draw.
    Weighted Random = Randomized. Early bonus are more likely to have low magic cost cards, later bonus draw are more likely to have higher cost cards. (No key cards)
    Fully Random = Randomized; every card is equally likely to appear in the bonus draws. (No key cards).
    """
    display_name = "Randomize Bonus Draws"
    option_off = 0
    option_weighted_random = 1
    option_fully_random = 2
    default = 1

class RandomizeEnemies(Toggle):
    """Choose to randomize every non-unique enemy in the game. Every instance of enemy X will become enemy Y.
    Still very experimental, so play at your own risk. If the game crashes, lags, or becomes corrupted; please report
    with logs."""
    display_name = "Randomize Enemies"
    default = 0

class RandomizeMagicCosts(Choice):
    """Choose to randomize the magic stone cost of every card to between the set minimal
    and maximum values. Shuffle swaps the vanilla costs randomly, maintaining the same distribution.
     Warning: This can trivialize the game"""
    display_name = "Randomize Magic Costs"
    option_off = 0
    option_on = 1
    option_shuffle = 2
    default = 0

class RandomizeMagicCostsMin(Range):
    """The minimum magic cost a card can be if Randomize magic Costs is enabled."""
    range_start = 0
    range_end = 20
    default = 0

class RandomizeMagicCostsMax(Range):
    """The maximum magic cost a card can be if Randomize magic Costs is enabled."""
    range_start = 0
    range_end = 20
    default = 15

class MagicCostsMultiplier(Range):
    """Multiplies all the of the magic stone costs by amount divided by 100;
    So 100 means no multiplier, 50 means half cost, 200 means double, etc.
    Takes place after any randomization and is clamped by what the game allows."""
    range_start = 0
    range_end = 1000
    default = 100

class RandomizeCardPrices(Choice):
    """Choose to randomize the buy/sell costs of every card to between the set minimal
    and maximum values. Shuffle swaps the vanilla costs randomly, maintaining the same distribution.
    Cards always sell for approximately 2/3 of their price.
    """
    display_name = "Randomize Card Prices"
    option_off = 0
    option_on = 1
    option_shuffle = 2
    default = 0

class RandomizeCardPricesMin(Range):
    """The minimum price a card can have if Randomize Card Prices is enabled."""
    range_start = 0
    range_end = 9999
    default = 0

class RandomizeCardPricesMax(Range):
    """The maximum price a card can have if Randomize Card Prices is enabled."""
    range_start = 0
    range_end = 9999
    default = 2000

class CardPricesMultiplier(Range):
    """Multiplies all the of the card prices by amount divided by 100;
    So 100 means no multiplier, 50 means half cost, 200 means double, etc
    Takes place after any randomization and is clamped by what the game allows."""
    range_start = 0
    range_end = 1000
    default = 100

class RandomizeCopyXPCosts(Choice):
    """Choose to randomize the Copy XP cost of every card to between the set minimal
    and maximum values. Shuffle swaps the vanilla costs randomly, maintaining the same distribution."""
    display_name = "Randomize Magic Costs"
    option_off = 0
    option_on = 1
    option_shuffle = 2
    default = 0

class RandomizeCopyXPCostsMin(Range):
    """The minimum Copy XP cost a card can have if Randomize magic Costs is enabled."""
    range_start = 0
    range_end = 65535
    default = 0

class RandomizeCopyXPCostsMax(Range):
    """The maximum Copy XP cost a card can have if Randomize magic Costs is enabled."""
    range_start = 0
    range_end = 65535
    default = 30000

class CopyXPCostsMultiplier(Range):
    """Multiplies all the of the Copy XP costs by amount divided by 100;
    So 100 means no multiplier, 50 means half cost, 200 means double, etc
    Takes place after any randomization and is clamped by what the game allows."""
    range_start = 0
    range_end = 1000
    default = 100

class RandomizeUpgradeXPCosts(Choice):
    """Choose to randomize the upgrade XP cost of every card to between the set minimal
    and maximum values. Shuffle swaps the vanilla costs randomly, maintaining the same distribution."""
    display_name = "Randomize Magic Costs"
    option_off = 0
    option_on = 1
    option_shuffle = 2
    default = 0

class RandomizeUpgradeXPCostsMin(Range):
    """The minimum upgrade XP cost a card can have if Randomize magic Costs is enabled."""
    range_start = 0
    range_end = 65535
    default = 0

class RandomizeUpgradeXPCostsMax(Range):
    """The maximum upgrade XP cost a card can have if Randomize magic Costs is enabled."""
    range_start = 0
    range_end = 65535
    default = 25000

class UpgradeXPCostsMultiplier(Range):
    """Multiplies all the of the Upgrade XP costs by amount divided by 100;
    So 100 means no multiplier, 50 means half cost, 200 means double, etc
    Takes place after any randomization and is clamped by what the game allows."""
    range_start = 0
    range_end = 1000
    default = 100

class LevelRandomization(Toggle):
    """Randomize which levels unlock when you would normally unlock a level.
    Note: Alenjah Castle still always leads to all the towers in order, and
    the sacred battle arena still leads to sacred battle arena 2. Proving Grounds
    is still unlocked only after beating the game. Nobleman's Residence is always
    the starting level.
    """
    display_name = "Level Randomization"
    default = 0

class MusicRandomization(Toggle):
    """Randomize the music that plays during levels"""
    display_name = "Level Music Randomization"
    default = 0

class CharacterModel(Choice):
    """Change your character model.
    Note: Models other than Tara do not have injured animations, and therefor are mechanically better.
    """
    display_name = "Character Model"
    option_Tara = 0
    option_Rashiannu = 1
    option_Leod = 2
    option_Katia = 3
    option_Helena = 4
    option_Thalnos = 5
    option_Stranger = 6
    option_Kendarie_Soldier = 7
    option_Tara_Alt = 8
    option_Rashiannu_Alt = 9
    option_Leod_Alt = 10
    option_Katia_Alt = 11
    option_Helena_Alt = 12
    option_Thalnos_Alt = 13
    option_Stranger_Alt = 14
    option_Kendarie_Soldier_Alt = 15
    default = 0


@dataclass
class LostKingdoms2Options(PerGameCommonOptions):
    win_condition : WinConditionOption
    collect_red_fairies_amount : CollectRedFariesAmount
    fairysanity : FairysanityConditionOption
    shopsanity: ShopsanityConditionOption
    combosanity: CombosanityConditionOption
    enemysanity: EnemysanityConditionOption
    breaksanity: BreaksanityOption
    open_world : OpenWorldConditionOption
    level_unlocks_as_items : LevelUnlocksAsItems
    exclude_sacred_battle_arena_checks: ExcludeSacredBattleArenaChecksOption
    progressive_leveling: ProgressiveLevelingOption
    progressive_attribute_proficiencies: ProgressiveAttributeProficienciesOption
    death_link: DeathLink
    randomize_starting_deck : RandomizeStartingDeck
    randomize_shop_contents : RandomizeShopContents
    randomize_bonus_draws : RandomizeBonusDraws
    randomize_levels : LevelRandomization
    randomize_enemies: RandomizeEnemies
    randomize_level_music: MusicRandomization
    character_model : CharacterModel
    randomize_magic_stone_costs: RandomizeMagicCosts
    randomize_magic_stone_costs_min: RandomizeMagicCostsMin
    randomize_magic_stone_costs_max: RandomizeMagicCostsMax
    magic_stone_costs_multiplier: MagicCostsMultiplier
    randomize_card_prices: RandomizeCardPrices
    randomize_card_prices_min: RandomizeCardPricesMin
    randomize_card_prices_max: RandomizeCardPricesMax
    card_prices_multiplier: CardPricesMultiplier
    randomize_copy_xp_costs: RandomizeCopyXPCosts
    randomize_copy_xp_costs_min: RandomizeCopyXPCostsMin
    randomize_copy_xp_costs_max: RandomizeCopyXPCostsMax
    copy_xp_cost_multiplier: CopyXPCostsMultiplier
    randomize_upgrade_xp_costs: RandomizeUpgradeXPCosts
    randomize_upgrade_xp_costs_min: RandomizeUpgradeXPCostsMin
    randomize_upgrade_xp_costs_max: RandomizeUpgradeXPCostsMax
    upgrade_xp_cost_multiplier: UpgradeXPCostsMultiplier