"""
Create SAC (Sony Automator Controls) icon for the application.
Generates both .ico and .png versions.
"""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path


def create_sac_icon(size=256):
    """Create SAC icon with concentric circles and lines to S, A, C."""
    # Create image with dark background matching app theme
    image = Image.new('RGBA', (size, size), (26, 26, 26, 255))
    dc = ImageDraw.Draw(image)

    cx, cy = size // 2, size // 2
    color = (0, 188, 212, 255)  # Teal accent color #00bcd4
    line_width = max(2, size // 32)

    # Draw concentric circles (matching Singular Controls style)
    for radius_factor in [0.35, 0.24, 0.13]:
        r = int(size * radius_factor)
        dc.ellipse([cx-r, cy-r, cx+r, cy+r], outline=color, width=line_width)

    # Draw lines to S, A, C letter positions
    outer_r = int(size * 0.35)

    # Line to S (top)
    dc.line([(cx, cy - outer_r), (cx, int(size * 0.05))], fill=color, width=line_width)

    # Line to A (bottom-left)
    dc.line([(cx - 4, cy + outer_r - 2), (int(size * 0.08), size - int(size * 0.08))], fill=color, width=line_width)

    # Line to C (right)
    dc.line([(cx + outer_r, cy), (size - int(size * 0.05), cy)], fill=color, width=line_width)

    # Draw small checkmark in center (quality/verified symbol)
    check_size = int(size * 0.08)
    dc.line([(cx - check_size, cy), (cx - 2, cy + check_size//2)], fill=color, width=line_width)
    dc.line([(cx - 2, cy + check_size//2), (cx + check_size, cy - check_size//2)], fill=color, width=line_width)

    return image


def main():
    """Generate icon files."""
    output_dir = Path(__file__).parent / "static"
    output_dir.mkdir(exist_ok=True)

    # Generate high-res PNG
    print("Creating high-res SAC icon (256x256)...")
    icon_256 = create_sac_icon(256)
    icon_256.save(output_dir / "sac_icon.png")
    print(f"[OK] Saved: {output_dir / 'sac_icon.png'}")

    # Generate multi-resolution ICO file
    print("\nCreating multi-resolution ICO file...")
    sizes = [16, 32, 48, 64, 128, 256]
    icons = [create_sac_icon(s) for s in sizes]

    ico_path = output_dir / "sac_icon.ico"
    icons[0].save(
        ico_path,
        format='ICO',
        sizes=[(s, s) for s in sizes],
        append_images=icons[1:]
    )
    print(f"[OK] Saved: {ico_path}")
    print(f"  Contains sizes: {', '.join(f'{s}x{s}' for s in sizes)}")

    print("\n[DONE] Icon generation complete!")
    print(f"\nGenerated files:")
    print(f"  - sac_icon.png (256x256)")
    print(f"  - sac_icon.ico (multi-resolution)")


if __name__ == "__main__":
    main()
