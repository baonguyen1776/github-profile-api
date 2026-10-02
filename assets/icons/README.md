# Technology icons

SVG icons from [Devicon](https://github.com/devicons/devicon), bundled locally under its [license](LICENSE.devicon).

Original assets remain available. The grouped badge renderer uses `badge-{slug}.svg` files downloaded from the official Devicon repository, preferring its plain variant and falling back to its original variant. Download source: `https://raw.githubusercontent.com/devicons/devicon/master/icons/{slug}/{slug}-{variant}.svg`.

The renderer recolors badge logos for contrast and embeds them as SVG data URLs, so the card needs no external image requests. Technologies without a bundled logo (currently GSAP, JAX, MediaPipe and SciPy) use a labeled abbreviation. Badge/icon mappings live in `renderers/stack.py`.
