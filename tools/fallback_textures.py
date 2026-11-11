"""Bind the port's model surfaces to its independent fallback artwork."""

from pathlib import PurePosixPath


FAMILIES = {
    'adjustable_chain_gearshift': 'chain_drive',
    'andesite_alloy_block': 'alloy_block',
    'andesite_casing': 'andesite_casing',
    'andesite_encased_shaft': 'andesite_casing',
    'basin': 'basin',
    'belt': 'belt_rubber',
    'belt_pulley': 'steel_axle',
    'brass_block': 'brass_block',
    'brass_casing': 'brass_casing',
    'brass_encased_shaft': 'brass_casing',
    'brass_funnel': 'brass_funnel',
    'chute': 'chute',
    'clockwork_bearing': 'clockwork',
    'clutch': 'clutch',
    'copper_casing': 'copper_casing',
    'crushing_wheel': 'crusher_wheel',
    'deepslate_zinc_ore': 'deepslate_zinc_ore',
    'deployer': 'deployer',
    'depot': 'depot_rim',
    'encased_chain_drive': 'chain_drive',
    'fluid_pipe': 'pipe_copper',
    'fluid_tank': 'fluid_tank',
    'fluid_valve': 'valve',
    'flywheel': 'flywheel',
    'funnel': 'andesite_funnel',
    'gantry_carriage': 'gantry_carriage',
    'gantry_shaft': 'gantry',
    'gearbox': 'gearbox',
    'gearshift': 'gearshift',
    'goggles': 'cranial_goggles',
    'hand_crank': 'hand_crank',
    'industrial_iron_block': 'industrial_iron',
    'mechanical_bearing': 'bearing',
    'mechanical_harvester': 'harvester',
    'mechanical_plough': 'plough',
    'mechanical_pump': 'pump',
    'piston_extension_pole': 'piston',
    'portable_storage_interface': 'cargo_dock',
    'raw_zinc_block': 'raw_zinc_block',
    'shaft': 'steel_axle',
    'shaft_half': 'steel_axle',
    'smart_chute': 'smart_chute',
    'speedometer': 'andesite_casing',
    'sticker': 'sticker',
    'stressometer': 'andesite_casing',
    'weathered_iron_block': 'weathered_iron',
    'windmill_bearing': 'windmill',
    'zinc_block': 'zinc_block',
    'zinc_ore': 'zinc_ore',
}

PART_MATERIALS = {
    'bearing/top': 'bearing',
    'bearing/top_wooden': 'windmill',
    'deployer/pole': 'steel_axle',
    'encased_fan/block': 'fan_case',
    'encased_fan/propeller': 'fan_blade',
    'fluid_valve/pointer': 'valve_handle',
    'gauge/dial': 'gauge_needle',
    'gauge/speedometer/head': 'speedometer',
    'gauge/stressometer/head': 'stressometer',
    'hand_crank/handle': 'hand_crank',
    'mechanical_crafter/arrow': 'brass_cog',
    'mechanical_crafter/belt': 'belt_rubber',
    'mechanical_crafter/belt_animated': 'belt_rubber',
    'mechanical_drill/block': 'drill_case',
    'mechanical_drill/head': 'drill_steel',
    'mechanical_mixer/block': 'mixer_case',
    'mechanical_mixer/head': 'cutting_steel',
    'mechanical_mixer/pole': 'steel_axle',
    'mechanical_press/block': 'press_case',
    'mechanical_press/head': 'cutting_steel',
    'mechanical_pump/cog': 'brass_cog',
    'portable_storage_interface/block_middle_powered': 'cargo_dock_powered',
    'rope_pulley/rope': 'rope',
    'rope_pulley/rope_half': 'rope',
    'rope_pulley/rope_coil': 'rope',
    'sail/sail_frame_fallback': 'chassis',
    'smart_chute/block_powered': 'smart_chute_powered',
    'sticker/block_powered': 'sticker_powered',
    'sticker/head': 'sticker_slide',
    'chute/block_window': 'chute_frame',
}


FACE_MATERIALS = {
    'depot/block': {'up': 'depot_top'},
    'gearbox/block': {'up': 'gearbox_cap', 'down': 'gearbox_cap'},
    'mechanical_press/block': {'up': 'press_plate', 'down': 'press_plate'},
    'encased_fan/block': {face: 'andesite_casing' for face in ('north', 'south', 'west', 'east')},
    'mechanical_drill/block': {face: 'andesite_casing' for face in ('north', 'south', 'west', 'east')},
    'gauge/speedometer/head': {'east': 'speedometer'},
    'gauge/stressometer/head': {'east': 'stressometer'},
    'speedometer/item': {'north': 'speedometer', 'east': 'speedometer'},
    'stressometer/item': {'north': 'stressometer', 'east': 'stressometer'},
    'bearing/top': {'up': 'bearing_cap'},
    'bearing/top_wooden': {'up': 'windmill_cap'},
    'sticker/head': {'up': 'sticker_pad'},
}


def material(name, category='block'):
    return f'create:{category}/fallback/{name}'


def block_material(name, slot, texture):
    family, _, part = name.partition('/')
    if texture == 'minecraft:block/glass':
        return 'tank_glass'
    if name in PART_MATERIALS:
        return PART_MATERIALS[name]
    if family == 'sail':
        return part.removesuffix('_sail_fallback') + '_canvas'
    if family.startswith(('cut_', 'polished_cut_', 'small_')) or family == 'layered_andesite':
        return family
    if family.startswith(('large_cogwheel', 'cogwheel')):
        return 'oak_cog'
    if family.startswith(('andesite_encased_cogwheel', 'andesite_encased_large_cogwheel')):
        return 'andesite_casing'
    if family.startswith(('brass_encased_cogwheel', 'brass_encased_large_cogwheel')):
        return 'brass_casing'
    if family in ('belt_casing', 'belt_cover'):
        return 'andesite_casing' if part.startswith('andesite_') else 'brass_casing'
    if family in ('funnel', 'brass_funnel') and part.endswith('_on'):
        return FAMILIES[family] + '_active'
    if family == 'blaze_burner':
        if 'super' in part:
            return 'superheated'
        if 'rods' in part:
            return 'cold_flame'
        if part.startswith('blaze/'):
            return 'burner_hot'
        if part.startswith('goggles'):
            return 'cranial_goggles'
        return 'burner_case'
    if family == 'chassis_fallback':
        if part.startswith('sticky_'):
            return 'sticky_piston'
        if slot in ('up', 'down'):
            return 'chassis_end'
        if part.startswith('radial_'):
            return 'chassis_radial'
        if part.startswith('secondary_'):
            return 'chassis_secondary'
        return 'chassis_linear'
    if family == 'deployer' and part.startswith('hand_'):
        return 'deployer_hand'
    if family == 'item_drain':
        return 'drain' if slot == 'grate' else 'pipe_copper'
    if family == 'mechanical_crafter':
        return {'frame': 'brass_casing', 'slot': 'chassis'}.get(slot, 'crafter')
    if family == 'mechanical_pump' and slot == 'outlet':
        return 'pump_rim'
    if family == 'mechanical_piston':
        return 'sticky_piston' if part.startswith('sticky/') else 'piston'
    if family == 'mechanical_saw':
        return 'cutting_steel' if part.startswith('blade_') else 'saw'
    if family == 'millstone':
        return 'millstone'
    if family == 'rope_pulley':
        return 'pulley'
    return FAMILIES[family]


def retarget(path, model):
    """Assign fallback materials and align the machine face UVs."""
    prefix = 'assets/create/models/'
    if not path.startswith(prefix):
        return
    category, _, name = path.removeprefix(prefix).removesuffix('.json').partition('/')
    texture_category = 'block' if category == 'entity' else category
    for slot, texture in model.get('textures', {}).items():
        if not texture.startswith('minecraft:'):
            continue
        if category == 'item':
            tile = name
        elif category == 'entity':
            tile = 'sail_canvas' if name == 'logistics_hat' else 'belt_rubber'
        else:
            tile = block_material(name, slot, texture)
        if tile is not None:
            model['textures'][slot] = material(tile, texture_category)
    if category == 'block' and (faces := FACE_MATERIALS.get(name)):
        textures = model['textures']
        textures.update({face: material(tile) for face, tile in faces.items()})
        for element in model['elements']:
            for face in element['faces'].keys() & faces.keys():
                element['faces'][face] = {'texture': f'#{face}', 'uv': [0, 0, 16, 16]}
    if category == 'block' and name in ('mechanical_saw/horizontal', 'mechanical_saw/vertical'):
        model['textures']['casing'] = material('andesite_casing')
        slot = 'south' if name.endswith('/horizontal') else 'up'
        for face, surface in model['elements'][0]['faces'].items():
            surface['texture'] = '#all' if face == slot else '#casing'
    if category == 'block' and name == 'chute/block_window':
        model['render_type'] = 'minecraft:cutout'
    if category == 'block' and name.startswith('mechanical_piston/') and '/block' in name and 'elements' in model:
        body = model['elements'][0]
        for face, slot in (('down', 'back'), ('up', 'inner')):
            body['faces'][face] = {'texture': '#' + slot, 'uv': [0, 0, 16, 16]}
    for element in model.get('elements', []):
        for face in element['faces'].values():
            if face['texture'] in ('#filter', '#window'):
                face['uv'] = [0, 0, 16, 16]
    if name == 'fluid_tank/block_single_window':
        for element in model['elements']:
            for face in element['faces'].values():
                if face['texture'] == '#glass':
                    face['uv'] = [0, 0, 16, 16]


def texture_path(texture_id):
    return PurePosixPath('assets/create/textures') / (texture_id.removeprefix('create:') + '.png')
