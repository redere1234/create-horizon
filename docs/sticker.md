# Sticker

Place a Sticker so its head faces the block you want to move. A rising redstone
signal switches the head between extended and retracted. Losing power does not
change the head position. A Sticker placed beside an active signal starts
retracted.

A mechanical bearing can pick up a supported block at the extended head, or
pick up the Sticker by starting from that block. The other faces do not create
this bond. The facing and both redstone properties are saved with the block.
The original recipe uses two andesite alloy, one slimeball, two cobblestone
and one redstone dust. Original models are read from the optional local JAR.

The stationary head interpolates the original linear chase before applying
the quadratic offset. It emits the glue burst at the end of an extension
against a supportive block. The moving head uses the settled position.
Signal changes are evaluated after each Horizon neighbor update cascade.
Transient changes within one cascade, upward bounce, wrench handling and
computer integration remain open.

[Pinned Java StickerBlock](https://github.com/Creators-of-Create/Create/blob/ac0c444d9828da3453ae8cc65338e8de063286fb/src/main/java/com/simibubi/create/content/contraptions/chassis/StickerBlock.java) ·
[Pinned attachment check](https://github.com/Creators-of-Create/Create/blob/ac0c444d9828da3453ae8cc65338e8de063286fb/src/main/java/com/simibubi/create/impl/contraption/BlockMovementChecksImpl.java)
