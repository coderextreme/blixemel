import bpy
import os
import xml.etree.ElementTree as ET
import mathutils
from mathutils import Vector


# ------------------------------------------------------------
# BlenderXMLExporter
# ------------------------------------------------------------

class BlenderXMLExporter:
    def __init__(self, output_xml_path: str):
        self.output_xml_path = os.path.abspath(output_xml_path)
        self.output_dir = os.path.dirname(self.output_xml_path)
        self.texture_dir = os.path.join(self.output_dir, "textures")

    # ----------------- Public API -----------------

    def export(self):
        self._prepare_directories()
        print("--- START EXPORT ---")
        print(f"Source .blend: {bpy.data.filepath or '<unsaved session>'}")
        print(f"XML Output:     {self.output_xml_path}")
        print(f"Texture Folder: {self.texture_dir}")

        root = ET.Element("BlenderData", source=bpy.data.filepath or "")
        self._export_libraries(root)
        self._export_scenes(root)

        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        with open(self.output_xml_path, "wb") as f:
            tree.write(f, encoding="utf-8", xml_declaration=True)

        print("--- END EXPORT ---")

    # ----------------- Setup -----------------

    def _prepare_directories(self):
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir, exist_ok=True)
        if not os.path.exists(self.texture_dir):
            os.makedirs(self.texture_dir, exist_ok=True)

    # ----------------- Core helpers -----------------

    def _get_prop_info(self, obj, prop_identifier, prop_def):
        try:
            val = getattr(obj, prop_identifier)
            structure_type = ""
            if isinstance(val, mathutils.Vector):
                structure_type = "VECTOR"
                val_str = ",".join(map(str, val[:]))
            elif isinstance(val, mathutils.Euler):
                structure_type = "EULER"
                val_str = ",".join(map(str, val[:]))
            elif isinstance(val, mathutils.Quaternion):
                structure_type = "QUATERNION"
                val_str = ",".join(map(str, val[:]))
            elif isinstance(val, mathutils.Matrix):
                structure_type = "MATRIX_4X4" if len(val) == 4 else "MATRIX"
                val_str = ",".join(map(str, [col for row in val for col in row]))
            elif prop_def.type == 'POINTER':
                val_str = val.name if val else "None"
            elif prop_def.type in {'FLOAT_ARRAY', 'INT_ARRAY', 'BOOLEAN_ARRAY'}:
                val_str = ",".join(map(str, val)) if hasattr(val, "__iter__") else str(val)
            else:
                val_str = str(val)
            return val_str, prop_def.type, structure_type
        except:
            return "", "UNKNOWN", ""

    def _write_rna_properties(self, xml_element, blender_object):
        if hasattr(blender_object, "name"):
            xml_element.set("name", blender_object.name)
        if hasattr(blender_object, "type"):
            xml_element.set("type", getattr(blender_object, "type", ""))

        if not hasattr(blender_object, "bl_rna"):
            return

        props_container = ET.SubElement(xml_element, "Properties")

        # Explicit transform export (rotation_mode, matrix_world, rotation_euler, rotation_quaternion)
        rot_mode = getattr(blender_object, "rotation_mode", "XYZ")
        ET.SubElement(props_container, "Prop", {
            "name": "rotation_mode",
            "type": "STRING",
            "value": rot_mode
        })

        if hasattr(blender_object, "matrix_world"):
            mw = blender_object.matrix_world
            mw_str = ",".join(str(x) for row in mw for x in row)
            ET.SubElement(props_container, "Prop", {
                "name": "matrix_world",
                "type": "MATRIX_4X4",
                "value": mw_str,
                "structure_type": "MATRIX_4X4"
            })

        if hasattr(blender_object, "rotation_euler"):
            re = blender_object.rotation_euler
            ET.SubElement(props_container, "Prop", {
                "name": "rotation_euler",
                "type": "EULER",
                "value": f"{re.x},{re.y},{re.z}",
                "structure_type": "EULER"
            })

        if hasattr(blender_object, "rotation_quaternion"):
            rq = blender_object.rotation_quaternion
            ET.SubElement(props_container, "Prop", {
                "name": "rotation_quaternion",
                "type": "QUATERNION",
                "value": f"{rq.w},{rq.x},{rq.y},{rq.z}",
                "structure_type": "QUATERNION"
            })

        skip_props = {
            'matrix_basis', 'matrix_local', 'matrix_custom', 'matrix',
            'is_readonly', 'data'
        }

        if rot_mode == 'QUATERNION':
            skip_props.update({'rotation_euler', 'rotation_axis_angle'})
        elif rot_mode == 'AXIS_ANGLE':
            skip_props.update({'rotation_euler', 'rotation_quaternion'})
        else:
            skip_props.update({'rotation_quaternion', 'rotation_axis_angle'})

        for prop in blender_object.bl_rna.properties:
            if prop.is_readonly or prop.identifier in skip_props:
                continue

            val_str, type_str, struct_type = self._get_prop_info(blender_object, prop.identifier, prop)
            if type_str == 'POINTER' and (val_str == "None" or val_str == ""):
                continue

            attrs = {"name": prop.identifier, "type": type_str, "value": val_str}
            if struct_type:
                attrs["structure_type"] = struct_type
            ET.SubElement(props_container, "Prop", attrs)

    # ----------------- Geometry -----------------

    def _traverse_mesh_geometry(self, mesh_data, parent_node):
        mesh_node = ET.SubElement(parent_node, "Geometry")

        verts_node = ET.SubElement(mesh_node, "Vertices", {"count": str(len(mesh_data.vertices))})
        for v in mesh_data.vertices:
            ET.SubElement(verts_node, "V", {"co": f"{v.co.x},{v.co.y},{v.co.z}"})

        polys_node = ET.SubElement(mesh_node, "Polygons", {"count": str(len(mesh_data.polygons))})
        for p in mesh_data.polygons:
            ET.SubElement(polys_node, "P", {
                "i": ",".join(map(str, p.vertices)),
                "m": str(p.material_index)
            })

        if mesh_data.uv_layers:
            uvs_node = ET.SubElement(mesh_node, "UVLayers")
            for layer in mesh_data.uv_layers:
                layer_node = ET.SubElement(uvs_node, "Layer", {
                    "name": layer.name,
                    "active": str(layer.active_render)
                })
                for data in layer.data:
                    ET.SubElement(layer_node, "d", {"uv": f"{data.uv.x},{data.uv.y}"})

    # ----------------- Material / Nodes -----------------

    def _find_source_image(self, socket, visited=None):
        if not socket or not socket.is_linked:
            return None
        if visited is None:
            visited = set()

        link = socket.links[0]
        node = link.from_node
        if node in visited:
            return None
        visited.add(node)

        if node.type == 'TEX_IMAGE':
            return node.image

        next_socket = None
        if node.type == 'REROUTE':
            next_socket = node.inputs[0]
        elif node.type in {'NORMAL_MAP', 'BUMP', 'MAPPING', 'CURVE_RGB', 'VALTORGB', 'HUE_SAT'}:
            if "Color" in node.inputs:
                next_socket = node.inputs["Color"]
            elif "Factor" in node.inputs:
                next_socket = node.inputs["Factor"]
            elif len(node.inputs) > 0:
                next_socket = node.inputs[0]
        elif node.type in {'MIX_RGB', 'MIX_SHADER', 'ADD_SHADER'}:
            if len(node.inputs) > 2 and node.inputs[2].is_linked:
                next_socket = node.inputs[2]
            elif len(node.inputs) > 1 and node.inputs[1].is_linked:
                next_socket = node.inputs[1]
        elif node.type in {'SEPARATE_COLOR', 'SEPARATE_RGB', 'SEPARATE_XYZ'}:
            if len(node.inputs) > 0:
                next_socket = node.inputs[0]

        if next_socket:
            return self._find_source_image(next_socket, visited)
        return None

    def _export_full_node_graph(self, mat, mat_node):
        if not mat.node_tree:
            return

        tree = mat.node_tree
        ng = ET.SubElement(mat_node, "NodeGraph")
        node_map = {}

        for node in tree.nodes:
            n_el = ET.SubElement(ng, "Node", {
                "name": node.name,
                "type": node.bl_idname,
                "loc": f"{node.location.x},{node.location.y}",
            })

            if node.type == 'TEX_IMAGE' and getattr(node, "image", None):
                n_el.set("image", node.image.name)
            if hasattr(node, "label") and node.label:
                n_el.set("label", node.label)

            node_map[node] = n_el

        for link in tree.links:
            ET.SubElement(ng, "Link", {
                "from_node": link.from_node.name,
                "from_socket": link.from_socket.name,
                "to_node": link.to_node.name,
                "to_socket": link.to_socket.name,
            })

    def _export_material_nodes(self, mat, mat_node):
        if not mat.node_tree:
            return

        tree = mat.node_tree
        bsdf = next((n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        shader_node = ET.SubElement(mat_node, "ShaderGraph", {
            "type": "PRINCIPLED" if bsdf else "UNKNOWN"
        })

        def export_socket(sock_name, xml_attr, node_source=bsdf):
            if not node_source:
                return
            sock = node_source.inputs.get(sock_name)
            if not sock:
                return

            img = self._find_source_image(sock)
            if img:
                shader_node.set(f"{xml_attr}_image", img.name)
                print(f"  [Mat: {mat.name}] Mapped {xml_attr} -> Image: {img.name}")

            if not sock.is_linked:
                val = sock.default_value
                if hasattr(val, "__iter__"):
                    shader_node.set(f"{xml_attr}_val", ",".join(map(str, val)))
                else:
                    shader_node.set(f"{xml_attr}_val", str(val))

        if bsdf:
            export_socket("Base Color", "color")
            export_socket("Metallic", "metallic")
            export_socket("Roughness", "roughness")
            emission_name = "Emission Color" if "Emission Color" in bsdf.inputs else "Emission"
            export_socket(emission_name, "emission")
            export_socket("Alpha", "alpha")
            export_socket("Normal", "normal")
        else:
            img_node = next((n for n in tree.nodes if n.type == 'TEX_IMAGE' and n.image), None)
            if img_node:
                shader_node.set("color_image", img_node.image.name)

        # Hybrid: only export full node graph if more than 2 nodes
        if len(tree.nodes) > 2:
            self._export_full_node_graph(mat, mat_node)

    # ----------------- Libraries -----------------

    def _export_libraries(self, root):
        libs_node = ET.SubElement(root, "Libraries")

        # Images
        imgs_node = ET.SubElement(libs_node, "Images")
        for img in bpy.data.images:
            if img.type == 'IMAGE' and img.name not in ['Render Result', 'Viewer Node']:
                i_node = ET.SubElement(imgs_node, "Image")
                self._write_rna_properties(i_node, img)
                self._export_image_file(img, i_node)

        # Meshes
        meshes_node = ET.SubElement(libs_node, "Meshes")
        for mesh in bpy.data.meshes:
            m_node = ET.SubElement(meshes_node, "Mesh")
            self._write_rna_properties(m_node, mesh)
            self._traverse_mesh_geometry(mesh, m_node)
            mat_node = ET.SubElement(m_node, "MaterialSlots")
            for mat in mesh.materials:
                ET.SubElement(mat_node, "Slot", {"name": mat.name if mat else "None"})

        # Materials
        mats_node = ET.SubElement(libs_node, "Materials")
        for mat in bpy.data.materials:
            mat_node = ET.SubElement(mats_node, "Material")
            self._write_rna_properties(mat_node, mat)
            self._export_material_nodes(mat, mat_node)

        # Lights & Cameras
        for col_name, data_col, tag in [
            ("Lights", bpy.data.lights, "Light"),
            ("Cameras", bpy.data.cameras, "Camera")
        ]:
            node = ET.SubElement(libs_node, col_name)
            for item in data_col:
                self._write_rna_properties(ET.SubElement(node, tag), item)

        # Armatures
        arm_node = ET.SubElement(libs_node, "Armatures")

        for arm in bpy.data.armatures:
            a_node = ET.SubElement(arm_node, "ArmatureData")
            self._write_rna_properties(a_node, arm)

            bones_node = ET.SubElement(a_node, "Bones")

            # Find the armature object that uses this armature data
            arm_obj = next((obj for obj in bpy.data.objects if obj.data == arm), None)
            if not arm_obj:
                continue

            # Export bones using pose.bones (FBX stores rest pose here)
            for pbone in arm_obj.pose.bones:
                # Rest pose matrix in armature-local space
                m = pbone.matrix.copy()

                # Head is the translation of the matrix
                head = m.to_translation()

                # Tail = head + local Z axis * bone length
                direction = m.to_3x3() @ Vector((0.0, 0.0, pbone.bone.length))
                tail = head + direction

                ET.SubElement(bones_node, "Bone", {
                    "name": pbone.name,
                    "parent_name": pbone.parent.name if pbone.parent else "",
                    "head": f"{head.x},{head.y},{head.z}",
                    "tail": f"{tail.x},{tail.y},{tail.z}"
                })

        # Actions
        actions_node = ET.SubElement(libs_node, "Actions")
        for action in bpy.data.actions:
            act_node = ET.SubElement(actions_node, "Action")
            self._write_rna_properties(act_node, action)
            if hasattr(action, "fcurves"):
                for fcurve in action.fcurves:
                    fc_node = ET.SubElement(act_node, "FCurve", {
                        "data_path": fcurve.data_path,
                        "array_index": str(fcurve.array_index)
                    })
                    for kp in fcurve.keyframe_points:
                        ET.SubElement(fc_node, "KP", {
                            "co": f"{kp.co.x},{kp.co.y}",
                            "hl": f"{kp.handle_left.x},{kp.handle_left.y}",
                            "hr": f"{kp.handle_right.x},{kp.handle_right.y}",
                            "interpolation": kp.interpolation
                        })

    def _export_image_file(self, img, xml_node):
        try:
            safe_name = "".join(
                [c for c in img.name if c.isalpha() or c.isdigit() or c in ['_', '.']]
            ).rstrip()
            if not safe_name:
                safe_name = "Texture"
            if not safe_name.lower().endswith(('.png', '.jpg', '.jpeg')):
                safe_name += ".png"

            abs_path = os.path.join(self.texture_dir, safe_name)
            img.save_render(filepath=abs_path)
            xml_node.set("filepath", f"textures/{safe_name}")
            print(f"Saved Texture: {safe_name}")
        except Exception as e:
            print(f"Warning saving {img.name}: {e}")

    # ----------------- Scenes / Objects -----------------

    def _export_scenes(self, root):
        scenes_node = ET.SubElement(root, "Scenes")
        for scene in bpy.data.scenes:
            s_node = ET.SubElement(scenes_node, "Scene")
            self._write_rna_properties(s_node, scene)
            s_node.set("frame_start", str(scene.frame_start))
            s_node.set("frame_end", str(scene.frame_end))

            self._export_collection_recursive(scene.collection, s_node)
            # Also export any root-level objects directly under the scene
            for obj in scene.objects:
                if not obj.parent:
                    self._export_object_recursive(obj, s_node)

    def _export_collection_recursive(self, collection, parent_xml):
        col_node = ET.SubElement(parent_xml, "Collection", {"name": collection.name})
        self._write_rna_properties(col_node, collection)

        for obj in collection.objects:
            if not obj.parent:
                self._export_object_recursive(obj, col_node)

        for child_col in collection.children:
            self._export_collection_recursive(child_col, col_node)

    def _export_object_recursive(self, obj, parent_xml):
        obj_node = ET.SubElement(parent_xml, "Object")
        self._write_rna_properties(obj_node, obj)

        if obj.data:
            obj_node.set("data_name", obj.data.name)

        if obj.animation_data and obj.animation_data.action:
            obj_node.set("active_action", obj.animation_data.action.name)

        if obj.type == 'ARMATURE' and obj.pose:
            pose_node = ET.SubElement(obj_node, "Pose")
            for pbone in obj.pose.bones:
                pb_node = ET.SubElement(pose_node, "HBone", {"name": pbone.name})
                self._write_rna_properties(pb_node, pbone)

        if obj.animation_data and obj.animation_data.nla_tracks:
            nla_node = ET.SubElement(obj_node, "NLA")
            for track in obj.animation_data.nla_tracks:
                t_node = ET.SubElement(nla_node, "Track")
                self._write_rna_properties(t_node, track)
                for strip in track.strips:
                    s_node = ET.SubElement(t_node, "Strip")
                    self._write_rna_properties(s_node, strip)
                    if strip.action:
                        s_node.set("action_name", strip.action.name)

        if obj.modifiers:
            mods_node = ET.SubElement(obj_node, "Modifiers")
            for mod in obj.modifiers:
                m_node = ET.SubElement(mods_node, "Modifier")
                self._write_rna_properties(m_node, mod)

        if obj.vertex_groups:
            vg_node = ET.SubElement(obj_node, "VertexGroups")
            for vg in obj.vertex_groups:
                g_node = ET.SubElement(vg_node, "Group", {"name": vg.name})
                if obj.type == 'MESH':
                    for v in obj.data.vertices:
                        for g in v.groups:
                            if g.group == vg.index:
                                ET.SubElement(g_node, "VW", {
                                    "id": str(v.index),
                                    "w": str(g.weight)
                                })

        for child in obj.children:
            self._export_object_recursive(child, obj_node)


# ------------------------------------------------------------
# Convenience entry point (if run as a script)
# ------------------------------------------------------------

if __name__ == "__main__":
    bpy.ops.wm.open_mainfile(filepath="sandrunner_bike.blend")
    # bpy.ops.wm.open_mainfile(filepath="gramps_animated_full_1.blend")
    if bpy.data.filepath and "Program Files" not in bpy.data.filepath:
        base = os.path.splitext(bpy.data.filepath)[0]
    else:
        base = "C:/Users/jcarl/blixemel/scripts/sandrunner_bike"
    default_xml = base + ".blxml"

    exporter = BlenderXMLExporter(default_xml)
    exporter.export()
