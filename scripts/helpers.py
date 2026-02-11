import bpy
import os

# ------------------------------------------------------------
# Resolve texture directory next to .blend (Blender 5.0 safe)
# ------------------------------------------------------------

def resolve_texture_dir():
    blend_path = bpy.data.filepath
    if blend_path:
        base = os.path.splitext(os.path.basename(blend_path))[0]
        tex_dir = os.path.join(os.path.dirname(blend_path), f"{base}_textures")
    else:
        # Unsaved .blend fallback
        tex_dir = os.path.join(os.getcwd(), "unsaved_blend_textures")

    if not os.path.exists(tex_dir):
        os.makedirs(tex_dir, exist_ok=True)

    return tex_dir


# ------------------------------------------------------------
# Save Blender image as PNG (Blender 5.0 safe)
# ------------------------------------------------------------

def save_image_as_png(img, tex_dir):
    if not img:
        return None

    # Determine filename
    name = img.name
    if not name.lower().endswith(".png"):
        filename = f"{name}.png"
    else:
        filename = name

    path = os.path.join(tex_dir, filename)

    # Save image
    img.filepath_raw = path
    img.file_format = 'PNG'
    img.save()

    return filename


# ------------------------------------------------------------
# Load image from disk if it exists
# ------------------------------------------------------------

def load_image_if_exists(tex_dir, filename):
    if not filename or filename == "NONE":
        return None

    path = os.path.join(tex_dir, filename)
    if not os.path.exists(path):
        return None

    return bpy.data.images.load(path)


# ------------------------------------------------------------
# Create an in‑memory magenta placeholder (Texture Paint only)
# ------------------------------------------------------------

def create_magenta_placeholder():
    img = bpy.data.images.new("MagentaPlaceholder", width=1024, height=1024)
    pixels = [1.0, 0.0, 1.0, 1.0] * (1024 * 1024)
    img.pixels = pixels
    return img


# ------------------------------------------------------------
# Create a TEX_IMAGE node and assign an image (Blender 5.0 safe)
# ------------------------------------------------------------

def ensure_tex_image_node(mat, image):
    if not mat.node_tree:
        mat.use_nodes = True

    nt = mat.node_tree

    # Create a new TEX_IMAGE node
    tex_node = nt.nodes.new("ShaderNodeTexImage")
    tex_node.image = image

    # Set as active paint slot (Blender 5.0 paint system)
    nt.nodes.active = tex_node

    return tex_node

