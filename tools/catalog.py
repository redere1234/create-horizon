"""Implemented content only. IDs follow Create 6.0.10; assets are imported locally."""
from sail_content import COLORED_SAILS, SAIL_ITEMS
from chassis_content import CHASSIS
from portable_storage_content import PSI
from chute_content import CHUTE
from smart_chute_content import BLOCK as SMART_CHUTE
from funnel_content import BLOCK as FUNNEL, BRASS as BRASS_FUNNEL
from crushing_content import CONTROLLER as CRUSHER_CONTROLLER, WHEEL as CRUSHER
from crafter_content import CRAFTER, PARTS as CRAFTER_PARTS
from item_drain_content import BLOCK as ITEM_DRAIN
from fluid_tank_content import BLOCK as FLUID_TANK
from fluid_pipe_content import PIPE, PUMP, VALVE
from sticker_content import STICKER
from encased_cog_content import BLOCKS as ENCASED_COGS

BASE_BLOCKS = ['creative_motor', 'shaft', 'cogwheel', 'large_cogwheel', 'mechanical_press', 'depot']
TRANSMISSIONS = ['gearbox', 'clutch', 'gearshift', 'hand_crank', 'andesite_encased_shaft', 'brass_encased_shaft', 'encased_chain_drive', 'adjustable_chain_gearshift', 'flywheel']
STATIC_BLOCKS = ['andesite_casing', 'brass_casing', 'copper_casing', 'andesite_alloy_block', 'brass_block', 'zinc_block']
# All 14 Create stone types with every pattern and partial (palette_content.py).
from palette_content import PALETTE_NAMES, STONE_PALETTES
from window_content import CASINGS, WINDOW_PALETTE
IRON_PALETTE = ('industrial_iron_block', 'weathered_iron_block')
PALETTE_BLOCKS = list(WINDOW_PALETTE) + list(PALETTE_NAMES) + list(IRON_PALETTE)
ZINC_BLOCKS = ('zinc_ore', 'deepslate_zinc_ore', 'raw_zinc_block')
INSTRUMENTS = ['speedometer', 'stressometer']
GENERATORS = ['water_wheel', 'large_water_wheel']
PROCESSORS = ['millstone', 'encased_fan', 'mechanical_drill', 'basin', 'mechanical_mixer', 'blaze_burner', 'mechanical_bearing', 'windmill_bearing', 'clockwork_bearing', 'rope_pulley', CRAFTER, ITEM_DRAIN, FLUID_TANK, PIPE, PUMP, VALVE]
PISTONS = ['mechanical_piston', 'sticky_mechanical_piston', 'piston_extension_pole']
GANTRY = ['gantry_shaft', 'gantry_carriage']
ACTORS = ['mechanical_harvester', 'mechanical_saw', 'mechanical_plough', 'deployer']
INTERNAL_BLOCKS = ['water_wheel_structure', 'belt', 'lit_blaze_burner', 'mechanical_piston_head', 'rope', 'pulley_magnet', CRUSHER_CONTROLLER] + COLORED_SAILS
EXTRA_BLOCKSTATES = ['lit_blaze_burner', 'mechanical_piston_head', 'rope', 'pulley_magnet', CRUSHER_CONTROLLER] + COLORED_SAILS
EXTRA_MODELS = ['entity/train_hat', 'entity/logistics_hat']
BLOCKS = BASE_BLOCKS + TRANSMISSIONS + STATIC_BLOCKS + INSTRUMENTS + GENERATORS + PROCESSORS + PISTONS + GANTRY + ACTORS + SAIL_ITEMS + CHASSIS + [CHUTE, SMART_CHUTE, FUNNEL, BRASS_FUNNEL, CRUSHER, PSI, STICKER, *ZINC_BLOCKS] + PALETTE_BLOCKS
BLOCKS += ENCASED_COGS
BLOCKS += CASINGS
ITEMS = ['iron_sheet', 'golden_sheet', 'copper_sheet', 'andesite_alloy', 'brass_ingot', 'brass_nugget', 'zinc_ingot', 'zinc_nugget', 'wrench', 'brass_sheet', 'vertical_gearbox', 'goggles', 'propeller', 'wheat_flour', 'dough', 'belt_connector', 'whisk', 'empty_blaze_burner', 'blaze_cake', 'creative_blaze_cake']
ITEMS.append('super_glue')
SANDPAPERS = ['sand_paper', 'red_sand_paper']
ITEMS += ['rose_quartz', 'polished_rose_quartz', 'electron_tube', 'brass_hand'] + SANDPAPERS
ITEMS.extend(['raw_zinc', 'crafter_slot_cover', 'incomplete_precision_mechanism',
              'precision_mechanism', 'crushed_raw_copper', 'crushed_raw_gold', 'crushed_raw_iron',
              'crushed_raw_zinc', 'copper_nugget', 'powdered_obsidian', 'experience_nugget'])
HIDDEN_CREATIVE_ITEMS = {'incomplete_precision_mechanism', *ENCASED_COGS}
PARTS = ['shaft', 'shaft_half', 'cogwheel', 'large_cogwheel', 'creative_motor/block', 'creative_motor/block_vertical', 'mechanical_press/block', 'mechanical_press/head', 'depot/block', 'hand_crank/handle', 'hand_crank/block', 'gauge/dial', 'gauge/speedometer/head', 'gauge/stressometer/head', 'goggles', 'water_wheel/wheel', 'large_water_wheel/block', 'large_water_wheel/block_extension', 'millstone/block', 'millstone/inner', 'encased_fan/block', 'encased_fan/propeller', 'mechanical_drill/block', 'mechanical_drill/head']
PARTS += ['belt_pulley', 'belt/particle'] + ['belt/' + part for part in
    ['start', 'middle', 'end', 'start_bottom', 'middle_bottom', 'end_bottom',
     'diagonal_start', 'diagonal_middle', 'diagonal_end']]
PARTS += [f'belt_casing/{slope}_{part}' for slope in ('horizontal', 'diagonal', 'sideways')
          for part in ('start', 'middle', 'end', 'pulley')]
PARTS += [f'belt_cover/{material}_belt_cover_{axis}' for material in ('andesite', 'brass')
          for axis in ('x', 'z')]
PARTS += ['basin/block', 'basin/block_directional', 'mechanical_mixer/block',
          'mechanical_mixer/pole', 'mechanical_mixer/head', 'cogwheel_shaftless', 'flywheel/block', f'{CRUSHER}/block']
PARTS += ['large_cogwheel_shaftless']
PARTS += [f'{PUMP}/cog', f'{VALVE}/pointer']
PARTS += [f'{CRAFTER}/{part}' for part in CRAFTER_PARTS]
PARTS += ['bearing/top', 'bearing/top_wooden']
PARTS += ['rope_pulley/' + name for name in ('rope_coil', 'rope', 'pulley_magnet', 'rope_half', 'rope_half_magnet')]
PARTS += ['mechanical_harvester/blade'] + [
    f'mechanical_saw/blade_{orientation}_{state}'
    for orientation in ('horizontal', 'vertical')
    for state in ('active', 'inactive', 'reversed')
]
PARTS += ['deployer/pole', 'deployer/hand_pointing', 'deployer/hand_holding', 'deployer/hand_punching']
PARTS += [f'{PSI}/{part}' for part in ('block_middle', 'block_middle_powered', 'block_top')]
PARTS += [f'{STICKER}/head']
PARTS += ['blaze_burner/' + part for part in
          ['block', 'blaze/inert', 'blaze/idle', 'blaze/active', 'blaze/super', 'blaze/super_active',
           'goggles', 'goggles_small', 'flame', 'rods_small', 'rods_large',
           'superheated_rods_small', 'superheated_rods_large']]


def rust_catalog():
    text = '// Generated by tools/content.py from tools/catalog.py. SPDX-License-Identifier: MIT\n'
    for name, values in [('BLOCKS', BLOCKS), ('EXTRA_BLOCKSTATES', EXTRA_BLOCKSTATES), ('EXTRA_MODELS', EXTRA_MODELS), ('ITEMS', ITEMS), ('PARTS', PARTS)]:
        prefix = 'pub const ' + name + ': &[&str] = &['
        inline = ', '.join('"' + value + '"' for value in values)
        if len(inline) <= 60 and len(prefix + inline + '];') <= 100:
            text += prefix + inline + '];\n'
        else:
            text += prefix + '\n' + ''.join('    "' + v + '",\n' for v in values) + '];\n'
    return text
