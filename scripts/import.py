import bpy
import xml.etree.ElementTree as ET
import ast
from mathutils import Vector, Euler, Color, Matrix, Quaternion

# Global list to store pointer links that need resolving after all objects exist
DEFERRED_LINKS = []

def clean_scene():
    """Cleans the current blender scene."""
    if bpy.context.active_object and bpy.context.active_object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()

    # Remove data blocks
    for collection in [bpy.data.meshes, bpy.data.materials, bpy.data.armatures,
                       bpy.data.actions, bpy.data.cameras, bpy.data.lights,
                       bpy.data.images]:
        for block in collection:
            collection.remove(block)

    # Clean collections
    for block in bpy.data.collections:
        if block.name != "Collection":
            bpy.data.collections.remove(block)

    global DEFERRED_LINKS
    DEFERRED_LINKS = []

def parse_typed_value(value_str, type_str):
    """
    Converts string to Blender type based on EXPLICIT xml type.
    """
    if value_str is None or value_str == "None":
        return None

    try:
        if type_str == 'STRING':
            return value_str
        elif type_str == 'BOOLEAN':
            return value_str == "True"
        elif type_str == 'INT':
            return int(value_str)
        elif type_str == 'FLOAT':
            return float(value_str)
        elif type_str in {'FLOAT_ARRAY', 'INT_ARRAY', 'BOOLEAN_ARRAY'}:
            # Expecting "1.0,2.0,3.0"
            if not value_str: return []
            # Check if it looks like a list
            str_vals = value_str.split(',')
            # Heuristic: Determine if float or int based on type_str
            if 'FLOAT' in type_str:
                return [float(x) for x in str_vals]
            elif 'INT' in type_str:
                return [int(x) for x in str_vals]
            return str_vals
        elif type_str == 'POINTER':
            # Return the name string, to be resolved later
            return value_str
        elif type_str == 'ENUM':
            return value_str
    except Exception:
        return None
    return value_str

def apply_xml_properties(blender_obj, xml_node):
    """
    Iterates <Properties> child node and applies values.
    """
    props_container = xml_node.find("Properties")
    if props_container is None:
        return

    for prop in props_container.findall("Prop"):
        prop_name = prop.get("name")
        prop_type = prop.get("type")
        prop_val_str = prop.get("value")

        # Skip read-only or problematic properties usually handled by structure
        if prop_name in ['name', 'type', 'is_readonly']:
            continue

        val = parse_typed_value(prop_val_str, prop_type)

        if prop_type == 'POINTER':
            # Queue this for later. We cannot link an object that might not exist yet.
            if val and val != "None":
                DEFERRED_LINKS.append((blender_obj, prop_name, val))
        else:
            try:
                # Handle special Mathutils types conversion from Arrays
                # Blender API expects Sequences for properties like location,
                # but explicit types for specific props like Matrix might need help.
                if hasattr(blender_obj, prop_name):
                    setattr(blender_obj, prop_name, val)
            except Exception:
                # Some properties are read-only at runtime or depend on context
                pass

def build_mesh_geometry(mesh_data, mesh_xml_node):
    """
    Reconstructs vertices and faces from XML data.
    """
    verts = []
    faces = []

    # 1. Parse Vertices
    v_node = mesh_xml_node.find("Vertices")
    if v_node:
        for v in v_node.findall("V"):
            co_str = v.get("co")
            if co_str:
                verts.append([float(x) for x in co_str.split(',')])

    # 2. Parse Polygons (Faces)
    p_node = mesh_xml_node.find("Polygons")
    if p_node:
        for p in p_node.findall("P"):
            idx_str = p.get("i")
            if idx_str:
                faces.append([int(x) for x in idx_str.split(',')])

    # 3. Build Mesh
    mesh_data.from_pydata(verts, [], faces)
    mesh_data.update()

def import_actions(root):
    """Reconstructs Actions based on Typed Properties."""
    for action_node in root.findall(".//Action"):
        name = action_node.get("name", "ImportedAction")
        action = bpy.data.actions.new(name=name)

        apply_xml_properties(action, action_node)

        for fcurve_node in action_node.findall("FCurve"):
            # FCurve props are likely inside <Properties> now too,
            # but data_path and index are usually structural attributes in export
            # If your export put them in properties, retrieve them via lookups,
            # but usually key identifiers stay as attributes for finding the path.
            # Assuming export kept basic attributes for identifiers:

            # Helper to check attributes or property children
            def get_val(node, key):
                # Try attribute first
                if node.get(key): return node.get(key)
                # Try property child
                prop = node.find(f"Properties/Prop[@name='{key}']")
                if prop is not None: return prop.get("value")
                return None

            data_path = get_val(fcurve_node, "data_path")
            array_index = int(get_val(fcurve_node, "array_index") or 0)

            if not data_path: continue

            fcurve = action.fcurves.new(data_path=data_path, index=array_index)

            # Keyframes
            for point_node in fcurve_node.findall("KeyFramePoints"):
                # "co" might be in properties now
                co_val = None

                # Check properties block for 'co'
                props = point_node.find("Properties")
                if props:
                    co_prop = props.find("Prop[@name='co']")
                    if co_prop:
                        co_val = parse_typed_value(co_prop.get("value"), "FLOAT_ARRAY")

                if not co_val:
                     # Fallback to attribute if export kept it mixed
                     co_str = point_node.get("co")
                     if co_str: co_val = [float(x) for x in co_str.split(',')]

                if co_val:
                    kf = fcurve.keyframe_points.insert(frame=co_val[0], value=co_val[1])
                    apply_xml_properties(kf, point_node)

def import_object(parent_node, collection):
    """Recursive object importer handling <Data> and <MeshData>."""

    for obj_node in parent_node.findall("Object"):
        name = obj_node.get("name", "NewObject")
        obj_type = obj_node.get("type", "EMPTY")

        # --- 1. Create Data Block ---
        data_block = None
        data_node = obj_node.find("Data")

        if obj_type == 'MESH':
            mesh_name = name + "_Mesh"
            if data_node and data_node.get("name"): mesh_name = data_node.get("name")
            data_block = bpy.data.meshes.new(mesh_name)

            # Reconstruct Geometry
            mesh_data_xml = data_node.find("MeshData") if data_node else None
            if mesh_data_xml:
                build_mesh_geometry(data_block, mesh_data_xml)

        elif obj_type == 'CAMERA':
            cam_name = name + "_Cam"
            data_block = bpy.data.cameras.new(cam_name)
        elif obj_type == 'LIGHT':
            light_name = name + "_Light"
            data_block = bpy.data.lights.new(light_name, type='POINT')
        elif obj_type == 'ARMATURE':
            arm_name = name + "_Arm"
            data_block = bpy.data.armatures.new(arm_name)

        # --- 2. Create Object ---
        obj = bpy.data.objects.new(name, data_block)
        collection.objects.link(obj)

        # --- 3. Apply Properties ---
        # Apply Object properties (Location, Rotation, etc.)
        apply_xml_properties(obj, obj_node)

        # Apply Data properties (Light energy, Camera lens, etc.)
        if data_block and data_node:
            apply_xml_properties(data_block, data_node)

        # --- 4. Special Handling (Armatures, Vertex Groups) ---

        # Vertex Groups
        vg_container = obj_node.find("VertexGroups")
        if vg_container:
            for grp in vg_container.findall("Group"):
                vg = obj.vertex_groups.new(name=grp.get("name"))
                # Vertex weights
                for v in grp.findall("Vertex"):
                    try:
                        vid = int(v.get("id"))
                        weight = float(v.get("weight"))
                        # Verify vertex exists (important now that we have geometry)
                        if obj.type == 'MESH' and vid < len(obj.data.vertices):
                            vg.add([vid], weight, 'REPLACE')
                    except: pass

        # Armature Bones
        arm_node = obj_node.find("Armature")
        if arm_node and obj.type == 'ARMATURE':
            import_armature_bones(obj, arm_node)

        # Recurse Children
        import_object(obj_node, collection)

def import_armature_bones(obj, armature_node):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')

    def create_bones_recursive(xml_parent, bone_parent):
        for bone_xml in xml_parent.findall("Bone"):
            name = bone_xml.get("name")
            eb = obj.data.edit_bones.new(name)

            # Apply properties (Head/Tail/Roll)
            # These are likely in <Properties> now
            apply_xml_properties(eb, bone_xml)

            if bone_parent:
                eb.parent = bone_parent

            create_bones_recursive(bone_xml, eb)

    create_bones_recursive(armature_node, None)
    bpy.ops.object.mode_set(mode='OBJECT')

def import_collections(parent_xml, parent_col):
    for col_node in parent_xml.findall("Collection"):
        name = col_node.get("name", "Col")
        new_col = bpy.data.collections.new(name)
        parent_col.children.link(new_col)

        # Recurse contents
        import_object(col_node, new_col)
        import_collections(col_node, new_col)

def resolve_deferred_links():
    """
    Pass 2: Connect pointers (Parenting, Modifiers, Object Constraints)
    now that all objects exist.
    """
    print(f"Resolving {len(DEFERRED_LINKS)} pointers...")

    for obj, prop_name, target_name in DEFERRED_LINKS:
        # Find target in common data blocks
        target = bpy.data.objects.get(target_name) or \
                 bpy.data.materials.get(target_name) or \
                 bpy.data.actions.get(target_name) or \
                 bpy.data.armatures.get(target_name) or \
                 bpy.data.cameras.get(target_name) or \
                 bpy.data.lights.get(target_name) or \
                 bpy.data.images.get(target_name)

        if target:
            try:
                setattr(obj, prop_name, target)
            except Exception as e:
                print(f"Failed to link {prop_name} on {obj.name} to {target_name}: {e}")
        else:
            print(f"Warning: Link target '{target_name}' not found for {obj.name}.{prop_name}")

def importFromXML(infile):
    tree = ET.parse(infile)
    root = tree.getroot()

    clean_scene()

    # 1. Global Definitions
    import_actions(root)

    # 2. Scene Graph
    scenes_node = root.find("Scenes")
    if scenes_node is not None:
        for scene_node in scenes_node.findall("Scene"):
            scene = bpy.data.scenes.new(name=scene_node.get("name", "Scene"))
            bpy.context.window.scene = scene

            master_col = scene.collection

            import_collections(scene_node, master_col)
            import_object(scene_node, master_col)

            apply_xml_properties(scene, scene_node)

    # 3. Resolve Pointers
    resolve_deferred_links()

    print(f"Import Complete: {infile}")

# --- Execution ---
import_file_path = "sandrunner_bike.blxml"
import_path_abs = bpy.path.abspath("//" + import_file_path)

try:
    importFromXML(import_path_abs)
except FileNotFoundError:
    print(f"File not found: {import_file_path}")
except Exception as e:
    import traceback
    traceback.print_exc()
