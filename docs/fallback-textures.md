# Built-in textures and models

The mod ships independently made 16 × 16 pixel art. ImageGen produced the
material sheets and inventory sprites from written descriptions of the
Create 6.0.10 palette and silhouettes. The mod's fallback render shapes are
independent of its selection and collision shapes. Create's own resources take priority
when a player supplies the pinned JAR. [Install the original resources](assets.md)

Block materials fill each tile. Inventory sprites preserve transparent
padding. The tank window has its own alpha channel. The motor uses separate
output, side, back and base plates with one dark perimeter color. The
wheel meshes use separate beam grain, paddle boards, sawn ends and iron.
Wood and sail colors derive from their corresponding generated base tiles.

For new art, describe the material, silhouette, edge colors and face roles
before generating the sheet. Export the exact cells with nearest-neighbor
sampling, then check the tile on every face that uses it. When changing a
shared edge, check both faces in the game. Use the texture gallery to compare
the built-in art and the local JAR from the same viewpoints. Red sign text
marks the machines revised after the first gallery review. The bench near
the entrance shows a connected chain drive, live gauges and both active
burner colors. Block items use an isometric GUI transform. Standalone sprites
keep their flat inventory presentation.

Run `python3 tools/content.py` with Python 3.10 or later to regenerate the
bundled assets and `python3 tools/check_distribution.py` to check the
source-install package. Keep the original textures and reference JAR in
local development storage.

## Motor and wheel materials

| Tile | Surface |
| --- | --- |
| `motor_output` | Muted plum rim with a recessed square bearing |
| `motor_side` | Matched plum rim with charcoal vent ribs |
| `motor_back` | Dark lattice and a small central port |
| `motor_base` | Dark lower plate and grey bolts |
| `wheel_iron` | Dull grey-green metal for wheel hubs and motor rails |
| `wheel_<wood>_beam` | Lengthwise timber grain on braces and edges |
| `wheel_<wood>_plank` | Joined boards on the paddles and rim |
| `wheel_<wood>_end` | Sawn end grain where the beam terminates |
| `<color>_canvas` | Dyed canvas derived from the woven base tile |
| `tank_glass` | Copper-edged glass with a transparent center |

## Kinetics

Tiles in `block/fallback/`.

| Tile | Surface or silhouette |
| --- | --- |
| `steel_axle` | Straight gray green iron shaft surface, one subdued center ridge, vertical grain |
| `oak_cog` | Medium warm oak timber, three broad curved spoke-grain tracks, subtle dark joints |
| `andesite_casing` | Gray green cast frame around warm brown vertical wooden inset |
| `brass_casing` | Golden brass bevel frame around dark walnut wood inset |
| `copper_casing` | Orange salmon copper rim around charcoal gray vertical ribbed inset |
| `gearbox` | Gray green iron bezel, brown timber panel, black central square bearing socket |
| `gearbox_cap` | Gray green iron bezel, brown timber, centered square endgrain inset, no hole |
| `clutch` | Gray green metal rails, brown longitudinal wood panels, dark red central crossbar |
| `clutch_powered` | Same wood and gray iron rails, bright deep red central crossbar |
| `gearshift` | Brown wood center, gray green rails, thin dark red longitudinal strips |
| `gearshift_powered` | Same brown center and rails, brighter red strips on both sides |
| `chain_drive` | Parallel brown links with steel rails. Blockstate rotations align the run. |
| `chain_middle`, `chain_end` | Shaft sockets with links passing through or returning at the end |
| `chain_indicator`, `chain_indicator_powered` | Dark or bright red square on the adjustable gearshift housing |
| `hand_crank` | Warm brown wood grain lengthwise with charcoal ferrule at each end |
| `flywheel` | Golden brass band along both long edges, dark russet center strip |
| `speedometer` | Gray square gauge inset with pale face, muted green and warm amber graduations, no lettering, with the pointer drawn separately |
| `stressometer` | Gray square gauge inset with pale face and subdued cyan to red marks, no lettering, with the pointer drawn separately |

## Processing

Tiles in `block/fallback/`.

| Tile | Surface or silhouette |
| --- | --- |
| `press_case` | Brown wooden inset with olive gray iron frame, vertical planks |
| `press_plate` | Dark steel square recessed ram base, stepped slate grey edge |
| `depot_rim` | Gray green squared steel rim framing warm wood side slats |
| `depot_top` | Charcoal slate square tray face with gray stepped concentric rim |
| `millstone` | Mottled cool pale grey coarse stone with a few narrow radial grooves |
| `fan_case` | Pale green grey steel faceplate with simple narrow radial reinforcement and bolts |
| `fan_blade` | Bright grey white steel blade finish, restrained straight lengthwise silver highlight |
| `drill_case` | Graphite steel sleeve with raised dark square inset and small olive bevel |
| `cutting_steel` | Dark cool iron stepped horizontal tool bevel and silver cutting edge |
| `basin` | Near-black gunmetal basin wall, shallow rectangular embossed facets, gray upper rim |
| `mixer_case` | Medium brown timber pane, grey green iron frame and one pale grey horizontal middle band |
| `burner_case` | Blue-charcoal wrought iron cage bar material with warm grey edges |
| `burner_hot` | Golden amber fire-creature face tile, two dark pixel eyes and orange bottom |
| `crusher_wheel` | Warm oak body with worn steel at the corners |
| `brass_cog` | Dull mustard brass with an ochre edge and recessed dark gold center |
| `cold_flame` | Orange-gold hot bars with small bright yellow highlights, matte on dark charcoal |
| `burner_fire`, `burner_soul_fire` | Warm orange or blue flame silhouettes for the fallback burner renderer |
| `drill_steel`, `saw_disc` | Tapered steel drill material and toothed saw silhouette |

## Transport

Tiles in `block/fallback/`.

| Tile | Surface or silhouette |
| --- | --- |
| `belt_rubber` | Very dark brown graphite rubber, subtle horizontal fine tread, repeat-safe top and bottom edges |
| `chute`, `chute_frame`, `chute_window` | Dark steel chute shell, frame and transparent inspection opening |
| `smart_chute`, `smart_chute_powered` | Brass-rimmed shell with dark steel or red lower housing |
| `smart_chute_filter` | Brass inset aligned with the filter on all four sides |
| `brass_funnel`, `brass_funnel_active` | Brass or warm copper side panels |
| `brass_funnel_filter` | Brass-edged recess at the vertical funnel's filter control |
| `andesite_funnel` | Desaturated gray green steel bezel, squared dark gray opening |
| `andesite_funnel_active` | Same gray metal with wider black mouth and muted darker lip |
| `crafter` | Brown wooden strip around a bright brass square inset and dark work recess |
| `pipe_copper` | Salmon copper tubing surface with straight narrow copper highlight and dark russet rim |
| `pump`, `pump_rim` | Copper impeller housing and steel-banded oxidized joins |
| `valve`, `valve_handle` | Copper sleeve around a chamfered port and a red painted handle |
| `fluid_tank` | Muted orange salmon copper metal, subtle ribbing in center and horizontal seam bands |
| `drain` | Cool charcoal iron square grate, gray grid over black openings |
| `cargo_dock` | Dark steel face with antique brass edge plates and dark grey inset center |
| `cargo_dock_powered` | Same steel with warmer amber collar lines and inset dark steel center |

## Motion

Tiles in `block/fallback/`.

| Tile | Surface or silhouette |
| --- | --- |
| `piston` | Brown vertical wood inset inside green grey iron plate and dark steel shaft collar |
| `sticky_piston` | Same brown wood and olive metal with square translucent-looking green adhesive motif |
| `piston_case`, `piston_back` | Oak and steel housing with a separate rear plate and bore |
| `piston_head`, `piston_sticky_head` | Pale end grain with an inset rubber pad on the sticky model |
| `gantry` | Dark brick-red steel rack with angular red diagonal alternating teeth, dark edges |
| `gantry_carriage` | Dark steel slider with pale bronze insert and visible runners |
| `sticker`, `sticker_powered` | Wooden X brace housing with a red indicator when powered |
| `sticker_slide`, `sticker_pad` | Steel moving edge and green contact face |
| `bearing`, `bearing_cap` | Oak and steel housing with one distinct rotating flange |
| `windmill`, `windmill_cap` | Pale wood sleeve with a reinforced end grain cap |
| `clockwork` | Horizontal brass strip on dark charcoal iron with one gold square inset |
| `pulley` | Gray green outer plates and graphite dark cable drum recess |
| `rope` | Warm ochre hemp rope texture with repeated dark diagonal twists |
| `chassis` | Medium warm brown timber, dark horizontal wood seams and pale gray metal strap at edges |
| `chassis_linear`, `chassis_secondary`, `chassis_radial` | Distinct runs of boards and bracing along the machine axis |
| `chassis_end` | Reinforced wood grain on the axial faces |
| `harvester`, `harvester_reel` | Charcoal housing and contrasting steel teeth on the moving reel |
| `saw` | Dark charcoal housing and recessed blade slot |
| `plough` | Dark forged steel scraper with a light cutting bevel and small fasteners |
| `deployer`, `deployer_filter`, `deployer_hand` | Brass and steel body, recessed filter marker, and gold actuator |

## Masonry

Tiles in `block/fallback/`.

| Tile | Surface or silhouette |
| --- | --- |
| `cut_andesite` | Mid-grey medium flecked raw cut andesite, tileable pixel clusters |
| `polished_cut_andesite` | Smooth medium neutral grey stone with shallow bevel at perimeter |
| `cut_andesite_bricks` | Large medium grey staggered brick courses and slim charcoal mortar |
| `small_andesite_bricks` | Small mid grey staggered bricks, straight fine mortar |
| `layered_andesite` | Alternating ash gray and warm grey narrow horizontal bands |
| `cut_granite` | Mottled muted warm russet and dusty rose granite |
| `polished_cut_granite` | Smooth muted russet warm granite, subtle bevel |
| `cut_granite_bricks` | Large warm reddish brown brick courses and dark mortar |
| `small_granite_bricks` | Small muted brick red rectangular staggered masonry |
| `cut_diorite` | Pale ash ivory stone with soft gray mineral flecks |
| `polished_cut_diorite` | Smooth ash ivory stone with crisp pale gray bevel |
| `cut_diorite_bricks` | Large pale ivory staggered bricks with grey mortar |
| `small_diorite_bricks` | Small pale off-white grey staggered brick masonry |
| `zinc_block` | Desaturated silver-green cast zinc with straight vertical highlights and grey bevel |
| `brass_block` | Golden honey brass plate with ochre lower edge and sparse straight highlights |
| `alloy_block` | Gray green granular metal with subtle pale flecks, thin dark grey edge |

## Detail

Tiles in `block/fallback/`.

| Tile | Surface or silhouette |
| --- | --- |
| `zinc_ore` | Neutral grey stone with sparse pale green silver flecks in small angular patches |
| `deepslate_zinc_ore` | Layered dark gray black stone with a few pale green silver ore patches |
| `raw_zinc_block` | Irregular dark desaturated grey green mineral chunks, pale icy mint edges |
| `industrial_iron` | Charcoal grey recessed ridged metal panel with thin silver edging and corner rivets |
| `weathered_iron` | Dark charcoal metal bezel and brown oxidized gray iron vertical inset strips |
| `superheated` | White hot cyan and pale blue flame bars, slate indigo base |
| `cranial_goggles` | Dark leather brown panel with muted brass rims and two blue teal glass glints |
| `gauge_needle` | Red enamel needle surface, saturated vermilion streak with muted dark outer edge |
| `sail_canvas` | Warm off-white woven cotton, subtle near-white blocks and a narrow light beige sewn edge |

## Metals

Tiles in `item/fallback/`.

| Tile | Surface or silhouette |
| --- | --- |
| `iron_sheet` | Thin flat rhombus plate of silver gray iron, pale near edge, dark gray far edge |
| `golden_sheet` | Thin flat rhombus plate of golden yellow metal, pale yellow edge |
| `copper_sheet` | Thin flat rhombus plate of salmon orange copper with dark russet underside |
| `brass_sheet` | Thin flat rhombus plate of honey gold brass and muted ochre underside |
| `andesite_alloy` | Irregular gray green short stone-metal lump with light grey face |
| `brass_ingot` | Golden orange trapezoid bar, pale warm yellow top |
| `zinc_ingot` | Short desaturated mint silver trapezoid bar with dark green gray underside |
| `brass_nugget` | Tiny irregular golden amber nugget with one cream highlight |
| `zinc_nugget` | Tiny angular mint silver nugget with dark grey green edge |

## Ores

Tiles in `item/fallback/`.

| Tile | Surface or silhouette |
| --- | --- |
| `copper_nugget` | Small salmon orange angular nugget |
| `raw_zinc` | Rough compact cluster of light green gray ore chunks |
| `crushed_raw_copper` | Tiny pile of rust orange ore chunks with dark turquoise flecks |
| `crushed_raw_gold` | Tiny golden yellow ore chunks with dark ochre outline |
| `crushed_raw_iron` | Small cluster of warm gray and tan ore chips |
| `crushed_raw_zinc` | Small cluster of icy mint green pale ore chips |
| `powdered_obsidian` | Tiny heap of almost black purple coarse powder |
| `experience_nugget` | Tiny square faceted lime green pellet with a dark leaf green outline |
| `electron_tube` | Upright compact pink-red glass tube with silvery grey socket |

## Tools

Tiles in `item/fallback/`.

| Tile | Surface or silhouette |
| --- | --- |
| `wrench` | Angled golden brass open jaw spanner, long wooden brown grip and dark edge |
| `goggles` | Two small round turquoise blue lenses with bright brass rims and brown leather head strap |
| `belt_connector` | Dark gray brown rubber strip coiled into low loose loop |
| `propeller` | Four short pale grey metal blades radiating from a gray square hub |
| `whisk` | Small angled gray double-loop wire whisk with dark stubby grip |
| `super_glue` | Slanted vibrant leaf green glue tube with silver grey nozzle and dark cap |
| `sand_paper` | Thin folded sand-colored tan square sheet, dark fine speckles |
| `red_sand_paper` | Thin folded pale peach-red sandpaper sheet with dark rusty orange edges |
| `vertical_gearbox` | Compact gray and green steel cube with warm timber inset and upright short gray shaft |

## Components

Tiles in `item/fallback/`.

| Tile | Surface or silhouette |
| --- | --- |
| `brass_hand` | Small brass mechanical hand with dark sleeve and two articulated golden fingers |
| `crafter_slot_cover` | Small square pale golden tile with brown rim and inset plate |
| `precision_mechanism` | Round golden gear casing with pale yellow inner ticks and gray pin |
| `incomplete_precision_mechanism` | Unfinished copper-brown circular ring with a gray small insert |
| `rose_quartz` | Tall rough angular pink crystal shard with burgundy shadow and white glint |
| `polished_rose_quartz` | Small rounded cube-shaped coral pink crystal with pale top facet |
| `wheat_flour` | Little cream mound of fine flour with two scattered pale grains |
| `dough` | Small low beige ball with soft pale cream top |
| `blaze_cake` | Small round fiery pastry with orange brown body and molten warm yellow top |

## Fuel

Tiles in `item/fallback/`.

| Tile | Surface or silhouette |
| --- | --- |
| `creative_blaze_cake` | Small circular hot-magenta pink pastry with pale lilac hot ring and deep purple lower edge |

## Stone palettes

`tools/palette_content.py` draws the palette tiles procedurally from one
base colour per stone (natural, cut, polished, slab side, bricks, small
bricks, layered, cap and pillar). The andesite, granite and diorite tiles
from earlier releases are kept. Delete a tile and rerun `tools/content.py`
to redraw it.
