#!/usr/bin/env python3
"""Export MIT recipes/tags/selected loot from pinned Create, never assets."""
import json
import math
import subprocess
from common import CREATE, PINS, ROOT
from catalog import BLOCKS, INTERNAL_BLOCKS, IRON_PALETTE, ITEMS, PALETTE_BLOCKS, STONE_PALETTES, ZINC_BLOCKS
from funnel_content import BLOCK as FUNNEL, BRASS as BRASS_FUNNEL
from smart_chute_content import BLOCK as SMART_CHUTE
from crushing_content import WHEEL as CRUSHER
from crafter_content import CRAFTER
from item_drain_content import BLOCK as ITEM_DRAIN
from fluid_tank_content import BLOCK as FLUID_TANK
from fluid_pipe_content import PIPE, PUMP, VALVE
from sail_content import COLORED_SAILS, SAIL_ITEMS
from portable_storage_content import PSI
from chute_content import CHUTE
from sticker_content import STICKER
from encased_cog_content import BLOCKS as ENCASED_COGS
from window_content import CASINGS


VANILLA_LOG_FAMILIES = ['acacia', 'birch', 'cherry', 'dark_oak', 'jungle', 'mangrove', 'oak', 'spruce']


def runtime_wood_cutting():
    """RuntimeDataGenerator.cuttingRecipes for the pinned 1.21.1 vanilla registry."""
    recipes = {}

    def add(source, result, count=1):
        path = f'create/recipe/cutting/runtime_generated/compat/minecraft/{source}_to_{result}.json'
        recipes[path] = {
            'type': 'create:cutting', 'ingredients': [{'item': 'minecraft:' + source}],
            'processing_time': 50, 'results': [{'id': 'minecraft:' + result, 'count': count}],
        }

    families = [*((wood, ('log', 'wood'), 6) for wood in VANILLA_LOG_FAMILIES),
                ('crimson', ('stem', 'hyphae'), 6), ('warped', ('stem', 'hyphae'), 6),
                ('bamboo', ('block',), 3)]
    for wood, variants, plank_count in families:
        planks = f'{wood}_planks'
        for suffix in variants:
            unstripped = f'{wood}_{suffix}'
            stripped = f'stripped_{unstripped}'
            add(unstripped, stripped)
            add(stripped, planks, plank_count)
        for shape in ('stairs', 'slab', 'fence', 'fence_gate', 'door', 'trapdoor',
                      'pressure_plate', 'button', 'sign'):
            add(planks, f'{wood}_{shape}', 2 if shape == 'slab' else 1)
    return dict(sorted(recipes.items()))


def loot_for_horizon(value):
    """Use the 26.3 condition discriminator without changing the loot rules."""
    if isinstance(value, list):
        return [loot_for_horizon(entry) for entry in value]
    if not isinstance(value, dict):
        return value
    legacy_condition = isinstance(value.get('condition'), str) and 'type' not in value
    return {
        ('type' if legacy_condition and key == 'condition' else key): loot_for_horizon(entry)
        for key, entry in value.items()
    }


def dry_mixing(recipe):
    """The native Basin adapter's explicit item-only, unheated JSON contract.

    Do not drop unsupported fluid ingredients or accept a malformed ingredient
    as a simpler one. Original fluids/heated recipes belong to their own port.
    """
    def item_ingredient(value):
        if isinstance(value, str): return ':' in value
        if isinstance(value, list): return bool(value) and all(item_ingredient(v) for v in value)
        return (isinstance(value, dict) and set(value) in ({'item'}, {'tag'})
                and isinstance(next(iter(value.values())), str))
    def output(value):
        return (isinstance(value, dict) and set(value) <= {'id', 'count', 'chance', 'components'}
                and isinstance(value.get('id'), str) and ':' in value['id']
                and type(value.get('count', 1)) is int and 1 <= value.get('count', 1) <= 99
                and type(value.get('chance', 1)) in (int, float)
                and math.isfinite(value.get('chance', 1)) and 0 <= value.get('chance', 1) <= 1
                and isinstance(value.get('components', {}), dict))
    inputs, outputs = recipe.get('ingredients'), recipe.get('results')
    return (recipe.get('heat_requirement', 'none') == 'none'
            and type(recipe.get('processing_time', 0)) is int
            and -(1 << 31) <= recipe.get('processing_time', 0) < (1 << 31)
            and isinstance(inputs, list) and 1 <= len(inputs) <= 64
            and all(item_ingredient(i) for i in inputs)
            and isinstance(outputs, list) and 1 <= len(outputs) <= 4
            and all(output(o) for o in outputs))


def fluid_mixing(recipe):
    """Bounded unheated mixing: exact water/lava singles, ordinary items or
    NeoForge block tags. Keep the original predicate, never rewrite block tags
    as item tags or silently strip fluid/components/unknown codec fields.
    """
    ingredients = recipe.get('ingredients')
    if not isinstance(ingredients, list): return False
    items, fluids = [], []
    for ingredient in ingredients:
        if isinstance(ingredient, dict) and ingredient.get('type') == 'neoforge:single':
            if (set(ingredient) != {'type', 'fluid', 'amount'}
                    or ingredient['fluid'] not in ('minecraft:water', 'minecraft:lava')
                    or type(ingredient['amount']) is not int
                    or not 1 <= ingredient['amount'] < (1 << 31)): return False
            fluids.append(ingredient)
        elif isinstance(ingredient, dict) and ingredient.get('type') == 'neoforge:block_tag':
            if (set(ingredient) != {'type', 'tag'} or not isinstance(ingredient['tag'], str)
                    or ':' not in ingredient['tag']): return False
            # Only the validation copy uses a plain tag; the exported original
            # retains neoforge:block_tag for native BlockItem/default-state tests.
            items.append({'tag': ingredient['tag']})
        else: items.append(ingredient)
    return (1 <= len(fluids) <= 2
            and dry_mixing(dict(recipe, ingredients=items)))


def heated_mixing(recipe):
    """Source item-only heated/superheated codecs, using actual below-Basin heat.
    Fluid recipes retain their separately bounded unheated export policy.
    """
    return (recipe.get('heat_requirement') in ('heated','superheated')
            and dry_mixing(dict(recipe,heat_requirement='none')))


def compacting(recipe):
    """The same bounded Basin codec, selected by the real compacting type.

    Unimplemented fluid tags/results and unavailable Create ingredients remain
    rejected; no recipe is converted to a simpler predicate or fake output.
    """
    return (recipe.get('type') == 'create:compacting'
            and (dry_mixing(recipe) or fluid_mixing(recipe) or heated_mixing(recipe)))


def burner_data_maps(names, read):
    """Actual MIT data maps declared by CreateDataMaps (not item fuel tags).

    The pinned release has only the superheated file; regular fuel lookup uses
    the ordinary furnace fallback unless a pack provides its declared data map.
    Missing files stay missing. Do not synthesize an empty original definition.
    """
    result={}
    for kind in ['regular', 'superheated']:
        path='create/data_maps/item/'+kind+'_blaze_burner_fuels.json'
        source='src/generated/resources/data/'+path
        if source not in names: continue
        data=read(source)
        if set(data)!={'values'} or not isinstance(data['values'],dict):
            raise ValueError('Unsupported burner data map structure: '+source)
        for key,value in data['values'].items():
            if not isinstance(key,str) or ':' not in key:
                raise ValueError('Invalid burner fuel key: '+repr(key))
            time=value.get('burn_time') if isinstance(value,dict) and set(value)=={'burn_time'} else value
            if type(time) is not int or not 1<=time<(1<<31):
                raise ValueError('Unsupported burner fuel value: '+repr(value))
        result[path]=data
    return result


def main():
    base = 'src/generated/resources/data/'
    names = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', PINS['create_revision']], cwd=CREATE, text=True).splitlines()
    known = {'create:' + n for n in BLOCKS + ITEMS}
    known_blocks = {'create:' + n for n in BLOCKS + INTERNAL_BLOCKS}
    def read(name):
        return json.loads(subprocess.check_output(['git', 'show', PINS['create_revision'] + ':' + name], cwd=CREATE))
    def dependencies(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == 'item' and isinstance(child, str): yield child
                else: yield from dependencies(child)
        elif isinstance(value, list):
            for child in value: yield from dependencies(child)
    recipes = {}
    processing = {'create:milling', 'create:crushing', 'create:splashing', 'create:haunting', 'create:mixing', 'create:compacting',
                  'create:sandpaper_polishing', 'create:cutting', 'create:deploying', 'create:sequenced_assembly'}
    cooking = {'minecraft:smelting', 'minecraft:smoking', 'minecraft:blasting'}
    palette_recipes = {
        base + f'create/recipe/{name}_from_stone_types_{stone}_stonecutting.json'
        for stone, variants in STONE_PALETTES.items()
        for name in [*variants, stone]
    }
    palette_recipes.update(base + f'create/recipe/{name}_from_ingots_iron_stonecutting.json'
                           for name in IRON_PALETTE)
    for name in names:
        if not name.startswith(base + 'create/recipe/') or not name.endswith('.json'): continue
        r = read(name)
        kind = r.get('type', '')
        if kind == 'create:sequenced_assembly' and name != base + 'create/recipe/sequenced_assembly/precision_mechanism.json':
            continue
        if kind == 'create:deploying':
            gears = {'cogwheel.json', 'large_cogwheel.json'}
            inputs = r.get('ingredients', [])
            copper = (name.endswith(('_from_adding_wax.json', '_from_removing_wax.json',
                                     '_from_deoxidising.json'))
                      and len(inputs) == 2 and inputs[0].get('item', '').startswith('minecraft:')
                      and r.get('keep_held_item') is True)
            if name.rsplit('/', 1)[1] not in gears and not copper:
                continue
        if kind == 'create:mechanical_crafting' and name != base + f'create/recipe/mechanical_crafting/{CRUSHER}.json':
            continue
        palette_cut = kind == 'minecraft:stonecutting' and name in palette_recipes
        if not palette_cut and kind not in {'minecraft:crafting_shaped', 'minecraft:crafting_shapeless', 'create:pressing', 'create:item_application', 'create:mechanical_crafting'} | processing | cooking: continue
        if kind == 'create:mixing' and not (dry_mixing(r) or heated_mixing(r)):
            # These two actual source flows are the bounded first native fluid
            # integration. Other fluid/heat/component recipe codecs stay out.
            if name not in {base+'create/recipe/mixing/dough_by_mixing.json',
                            base+'create/recipe/mixing/mud_by_mixing.json'} or not fluid_mixing(r): continue
        if kind == 'create:compacting' and not compacting(r): continue
        # Conditional recipes depend on other mods and their ingredient codecs.
        if 'neoforge:conditions' in r: continue
        output = r.get('result', {})
        output = output if isinstance(output, str) else output.get('id')
        output = output or (r.get('results') or [{}])[0].get('id')
        outputs = [v['id'] for v in r.get('results', [])] or [output]
        if any(not isinstance(v, str) or not (v.startswith('minecraft:') or v in known) for v in outputs): continue
        deps = list(dependencies(r))
        if any(not (d.startswith('minecraft:') or d in known) for d in deps): continue
        # Processing recipes legitimately return vanilla items. Also retain the
        # real vanilla cooking recipes for supported Create ingredients (dough).
        if (output not in known and kind not in processing
                and not (kind in cooking and any(d in known for d in deps))
                and not palette_cut): continue
        recipes[name[len(base):]] = r
    recipes.update(runtime_wood_cutting())
    # Retain upstream tag contents. Horizon's loader drops unregistered entries,
    # as documented; this does not register or pretend to implement other items.
    tags = {}
    conventional = {}
    for metal in ['iron', 'gold', 'copper']:
        conventional['c:ingots/' + metal] = ['minecraft:' + metal + '_ingot']
        conventional['c:storage_blocks/' + metal] = ['minecraft:' + metal + '_block']
    for metal in ['iron', 'gold']:
        conventional['c:nuggets/' + metal] = ['minecraft:' + metal + '_nugget']
    for metal in ['iron', 'gold', 'copper']:
        conventional['c:raw_materials/' + metal] = [f'minecraft:raw_{metal}']
        conventional['c:storage_blocks/raw_' + metal] = [f'minecraft:raw_{metal}_block']
    conventional['c:rods/wooden'] = ['minecraft:stick']
    conventional['c:dusts/redstone'] = ['minecraft:redstone']
    conventional['c:strings'] = ['minecraft:string']
    conventional['c:slimeballs'] = ['minecraft:slime_ball']
    # NeoForge's verified 1.21.1 convention contains this vanilla block item;
    # its optional legacy #forge alias is unavailable here and is omitted.
    conventional['c:netherracks'] = ['minecraft:netherrack']
    conventional['c:barrels/wooden'] = ['minecraft:barrel']
    colors = ['white','orange','magenta','light_blue','yellow','lime','pink','gray','light_gray','cyan','purple','blue','brown','green','red','black']
    conventional['c:glass_blocks'] = ['minecraft:glass', 'minecraft:tinted_glass'] + ['minecraft:' + color + '_stained_glass' for color in colors]
    conventional['c:glass_panes'] = ['minecraft:glass_pane'] + ['minecraft:' + color + '_stained_glass_pane' for color in colors]
    # NeoForge 21.1.227: the Crushing Wheel's six vanilla stones. Its legacy
    # #forge:stone entry is optional and absent in the pinned reference game.
    conventional['c:stones'] = ['minecraft:' + stone for stone in ['stone', 'granite', 'diorite', 'andesite', 'deepslate', 'tuff']]
    conventional['c:cobblestones'] = ['minecraft:cobblestone', 'minecraft:mossy_cobblestone', 'minecraft:cobbled_deepslate']
    conventional['c:gems/lapis'] = ['minecraft:lapis_lazuli']
    # NeoForge 21.1.227 convention values without its optional Forge aliases.
    conventional['c:gems/quartz'] = ['minecraft:quartz']
    # NeoForge 21.1.227 convention value used by the Scoria to Scorchia recipe.
    conventional['c:dyes/black'] = ['minecraft:black_dye']
    # NeoForge 21.1.227 colorless glass conventions used by the window recipes.
    conventional['c:glass_blocks/colorless'] = ['minecraft:glass']
    conventional['c:glass_panes/colorless'] = ['minecraft:glass_pane']
    conventional['c:sands/colorless'] = ['minecraft:sand']
    conventional['c:sands/red'] = ['minecraft:red_sand']
    conventional['create:not_upright_on_belt'] = []
    # NeoForge 21.1.227 convention tags used by Create's manual casing recipes.
    woods = VANILLA_LOG_FAMILIES
    conventional['c:stripped_logs'] = [
        *[f'minecraft:stripped_{wood}_log' for wood in woods],
        'minecraft:stripped_bamboo_block', 'minecraft:stripped_crimson_stem', 'minecraft:stripped_warped_stem',
    ]
    conventional['c:stripped_woods'] = [
        *[f'minecraft:stripped_{wood}_wood' for wood in woods],
        'minecraft:stripped_crimson_hyphae', 'minecraft:stripped_warped_hyphae',
    ]
    missing = []
    intrinsic_tags = ['create:upright_on_belt', 'create:not_upright_on_belt', 'create:sandpaper',
                      'c:flours', 'c:flours/wheat', 'c:foods/dough', 'c:foods/dough/wheat']
    pending = list(intrinsic_tags)
    def tag_refs(value):
        if isinstance(value, dict):
            for k,v in value.items():
                if k == 'tag': yield v
                else: yield from tag_refs(v)
        elif isinstance(value, list):
            for v in value: yield from tag_refs(v)
        elif isinstance(value,str) and value.startswith('#') and ':' in value: yield value[1:]
    for r in recipes.values(): pending.extend(tag_refs(r))
    while pending:
        namespace, path = pending.pop().split(':', 1)
        if namespace == 'minecraft': continue
        dest = namespace + '/tags/item/' + path + '.json'
        if dest in tags: continue
        name = base + dest
        if name not in names:
            fallback = conventional.get(namespace + ':' + path)
            if fallback is None:
                missing.append(namespace + ':' + path)
                continue
            tags[dest] = {'values': fallback}
        else:
            tags[dest] = read(name)
            # Upstream's datagen contains Create's additions only; supply the
            # vanilla side of convention tags alongside those additions.
            for value in conventional.get(namespace + ':' + path, []):
                if value not in tags[dest]['values']: tags[dest]['values'].append(value)
        pending.extend(tag_refs(tags[dest]))
    if missing: raise SystemExit('Missing convention definitions: ' + ', '.join(sorted(set(missing))))
    # Do not advertise furnace recipes whose only inputs are unimplemented ores.
    def available(value, seen=()):
        if isinstance(value, list): return any(available(v, seen) for v in value)
        if isinstance(value, dict):
            if value.get('type') == 'neoforge:single':
                return value.get('fluid') in ('minecraft:water', 'minecraft:lava')
            if 'item' in value: return available(value['item'], seen)
            if 'tag' in value: return available('#'+value['tag'], seen)
            if 'id' in value: return available(value['id'], seen)
            return False
        if value.startswith('#'):
            tag=value[1:]
            if tag.startswith('minecraft:'): return True
            if tag in seen: return False
            ns,path=tag.split(':',1)
            return available(tags.get(ns+'/tags/item/'+path+'.json',{}).get('values',[]),(*seen,tag))
        return value.startswith('minecraft:') or value in known
    def ingredients(r):
        if 'key' in r: return r['key'].values()
        return r.get('ingredients', [r.get('ingredient')])
    recipes={name:r for name,r in recipes.items() if all(available(i) for i in ingredients(r))}
    required=set()
    pending=intrinsic_tags + [tag for r in recipes.values() for tag in tag_refs(r)]
    while pending:
        ns,path=pending.pop().split(':',1)
        dest=ns+'/tags/item/'+path+'.json'
        if dest in required or dest not in tags: continue
        required.add(dest);pending.extend(tag_refs(tags[dest]))
    tags={name:t for name,t in tags.items() if name in required}
    zinc_blocks = {f'create:{name}' for name in ('zinc_block', *ZINC_BLOCKS)}
    for block_tag in ['mineable/axe', 'mineable/pickaxe', 'needs_iron_tool', 'beacon_base_blocks']:
        dest = f'minecraft/tags/block/{block_tag}.json'
        tag = read(base + dest)
        tag['values'] = [v for v in tag['values'] if isinstance(v, str) and v in known_blocks
                         and (block_tag.startswith('mineable/') or v in zinc_blocks)]
        tags[dest] = tag
    for kind in ['block', 'item']:
        dest = f'create/tags/{kind}/casing.json'
        tag = read(base + dest)
        tag['values'] = [value for value in tag['values'] if value in known_blocks]
        tags[dest] = tag
    # The static pickup adapter covers the two implemented iron palettes.
    dest = 'create/tags/block/wrench_pickup.json'
    tag = read(base + dest)
    tag['values'] = [value for value in tag['values'] if value in known_blocks]
    tags[dest] = tag
    # Fan catalyst and permeability tags are MIT behavior data. Unimplemented
    # Create blocks must not become required tag entries in the port.
    for kind, paths in {
        'block': ['fan_transparent', 'windmill_sails', 'plough_blacklist', 'plough_whitelist',
                  'fan_processing_catalysts/blasting', 'passive_boiler_heaters',
                  'fan_processing_catalysts/haunting', 'fan_processing_catalysts/smoking'],
        'fluid': ['fan_processing_catalysts/blasting', 'fan_processing_catalysts/splashing'],
        'entity_type': ['blaze_burner_capturable'],
    }.items():
        for path in paths:
            dest = 'create/tags/' + kind + '/' + path + '.json'
            tag = read(base + dest)
            def implemented(entry):
                name = entry if isinstance(entry, str) else entry.get('id', '')
                return name.startswith(('minecraft:', '#minecraft:')) or (kind == 'block' and name in known_blocks)
            tag['values'] = [entry for entry in tag['values'] if implemented(entry)]
            tags[dest] = tag
    # 1.21.1's source ID uses "convertable"; 26.3 renamed the vanilla tag to
    # "convertible". Keep the original recipe's actual BLOCK-tag predicate.
    # This is our convention definition for its three verified source members.
    tags['minecraft/tags/block/convertable_to_mud.json']={'values':[
        'minecraft:dirt','minecraft:coarse_dirt','minecraft:rooted_dirt']}
    maps=burner_data_maps(names,read)
    # Keep the complete source pool and explosion/random-sequence policy for
    # this newly supported block, rather than a generic unconditional drop.
    loot = {path: loot_for_horizon(read(base + path)) for path in [
        'create/loot_table/blocks/encased_chain_drive.json',
        'create/loot_table/blocks/adjustable_chain_gearshift.json',
        'create/loot_table/blocks/copper_casing.json',
        'create/loot_table/blocks/flywheel.json',
        'create/loot_table/blocks/mechanical_piston.json',
        'create/loot_table/blocks/sticky_mechanical_piston.json',
        'create/loot_table/blocks/piston_extension_pole.json',
        'create/loot_table/blocks/mechanical_piston_head.json',
        'create/loot_table/blocks/clockwork_bearing.json',
        'create/loot_table/blocks/mechanical_harvester.json',
        'create/loot_table/blocks/mechanical_saw.json',
        'create/loot_table/blocks/deployer.json',
        f'create/loot_table/blocks/{PSI}.json',
        f'create/loot_table/blocks/{CHUTE}.json',
        f'create/loot_table/blocks/{SMART_CHUTE}.json',
        f'create/loot_table/blocks/{FUNNEL}.json',
        f'create/loot_table/blocks/{BRASS_FUNNEL}.json',
        f'create/loot_table/blocks/{CRUSHER}.json',
        f'create/loot_table/blocks/{CRAFTER}.json',
        f'create/loot_table/blocks/{ITEM_DRAIN}.json',
        f'create/loot_table/blocks/{FLUID_TANK}.json',
        f'create/loot_table/blocks/{PIPE}.json',
        f'create/loot_table/blocks/{PUMP}.json',
        f'create/loot_table/blocks/{VALVE}.json',
        f'create/loot_table/blocks/{STICKER}.json',
        *[f'create/loot_table/blocks/{name}.json' for name in ENCASED_COGS],
        'create/loot_table/blocks/zinc_block.json',
        *[f'create/loot_table/blocks/{name}.json' for name in ZINC_BLOCKS],
        *[f'create/loot_table/blocks/{name}.json' for name in PALETTE_BLOCKS],
        *[f'create/loot_table/blocks/{name}.json' for name in CASINGS],
        *[f'create/loot_table/blocks/{name}.json' for name in SAIL_ITEMS + COLORED_SAILS],
    ]}
    feature = read(base + 'create/worldgen/configured_feature/zinc_ore.json')
    # 26.3 puts feature fields at the top level and uses an identifier for a
    # block state with no properties.
    ore = dict(type=feature['type'], **feature['config'])
    for target in ore['targets']:
        assert set(target['state']) == {'Name'}
        target['state'] = target['state']['Name']
    placed = read(base + 'create/worldgen/placed_feature/zinc_ore.json')
    # The Java config filter is a no-op at the default (generation enabled).
    # Keep the original count and height modifiers in their original order.
    assert placed['placement'].pop() == {'type': 'create:config_filter'}
    zinc_feature = {
        'create/worldgen/feature/zinc_ore.json': ore,
        'create/worldgen/placed_feature/zinc_ore.json': placed,
        'create/neoforge/biome_modifier/zinc_ore.json': read(base + 'create/neoforge/biome_modifier/zinc_ore.json'),
    }
    result = {'reference': PINS['create_revision'], 'license': 'MIT recipe/data-map/loot/worldgen data; original definitions of vanilla convention tags', 'recipes': recipes, 'tags': tags, 'data_maps':maps, 'loot_tables':loot, 'worldgen':zinc_feature}
    dest = ROOT / 'tools/data/recipes.json'; dest.parent.mkdir(exist_ok=True); dest.write_text(json.dumps(result, indent=2) + '\n')
    print('Exported', len(recipes), 'recipes,', len(tags), 'tags and',len(maps),'data maps from MIT datapack sources')


if __name__ == '__main__': main()
