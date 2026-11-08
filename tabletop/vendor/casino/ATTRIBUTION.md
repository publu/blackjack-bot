# Photographed materials and studio lighting

All files here are supplied by [Poly Haven](https://polyhaven.com) under [CC0](https://polyhaven.com/license). Original download URLs, checksums and authorship are recorded in `attribution.json`. No generated texture is used.

- [Polar Fleece](https://polyhaven.com/a/polar_fleece), photographed by **colormass**, processed by **Rico Cilliers**. Real photographed napped fabric, tinted green in the material as a visual approximation of casino cloth; this is not a scan of the physical robot table or a baize-specific material.
- [Leather White](https://polyhaven.com/a/leather_white), **Rob Tuytel**. Neutral photographed leather, tinted near-black for the padded rail (2K normal and roughness maps).
- [Studio Small 09](https://polyhaven.com/a/studio_small_09), **Sergej Majboroda**. Unclipped photographed HDR studio environment, available to the parent scene as an optional lighting asset.

Files are the original provider 1K JPG diffuse, OpenGL normal and roughness maps, plus 1K Radiance HDR. The diffuse maps use sRGB; normals and roughness are linear data. The environment requires a compatible RGBE/HDR loader and PMREM before use as scene lighting.

## Added for the casino look (Poly Haven, CC0)

- [Velour Velvet](https://polyhaven.com/a/velour_velvet), photographed by **colormass**, processed by **Rico Cilliers**. Kept for reference; the felt now uses procedural pile and mottling maps built in `casino-set.js`, so these files are not loaded.
- [Billiard Hall](https://polyhaven.com/a/billiard_hall) HDRI, **Greg Zaal** (photography), **Jarod Guest** (processing). 1K Radiance HDR, used as the room's image-based light and reflections.
- [Warm Bar](https://polyhaven.com/a/warm_bar) HDRI, **Greg Zaal** / **Jarod Guest**. 1K Radiance HDR, kept as an alternative environment.

The room (panelling, carpet, slot cabinets, sconces, pendant) and the chip, card-edge and felt-print art are drawn procedurally in `casino-set.js`; no other image assets are used.

## Casino floor (`casino-room.js`, files in `room/`, Poly Haven, CC0)

Downloaded 2026-11-08 from the Poly Haven API; original URLs, byte counts, SHA-256 and provider MD5 for every file are in `room/attribution.json`.

- [Dark Paneled Wood](https://polyhaven.com/a/dark_paneled_wood), **Dimitrios Savva**. 1K diffuse, OpenGL normal and roughness: the panelled wainscot, side walls and the coffered ceiling.
- [Floral Jacquard](https://polyhaven.com/a/floral_jacquard), photographed by **colormass**, processed by **Rico Cilliers**. 1K diffuse and OpenGL normal, tinted deep red in the material: the damask wall fabric.
- [Lacquered Cherry Wood](https://polyhaven.com/a/lacquered_cherry_wood), scanned by **Jenelle van Heerden**, processed by **Rico Cilliers**. 1K diffuse and roughness: skirting, chair rail, frieze, cornice and pilasters.
- [Marble 01](https://polyhaven.com/a/marble_01), **Rob Tuytel**. 1K diffuse and roughness: the two columns behind the dealer.
- [Dirty Carpet](https://polyhaven.com/a/dirty_carpet), **Rohit Seervi**. 1K OpenGL normal only: carpet pile under the procedurally drawn casino pattern.

Slot machines, reel strips, marquee and belly art, jackpot meters, video-slot screens, carpet pattern and baked light maps are drawn procedurally in `casino-room.js` (canvas textures); all game titles on them are invented. No downloadable slot-machine model met the licence and quality bar in the time available, so none is used.
