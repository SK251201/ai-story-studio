import bpy, json, os, sys
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if len(args) != 2:
    raise SystemExit("Expected shot.json and output frame prefix")
shot_path, prefix = args
shot = json.load(open(shot_path, encoding="utf-8"))
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE_NEXT"
scene.render.resolution_x = shot.get("width", 1920)
scene.render.resolution_y = shot.get("height", 1080)
scene.render.resolution_percentage = 100
scene.render.fps = shot.get("fps", 24)
scene.frame_start = 1
scene.frame_end = shot.get("frame_end", 120)
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = prefix
scene.view_settings.view_transform = "AgX"
scene.world = bpy.data.worlds.new("Studio World")
scene.world.use_nodes = True
scene.world.node_tree.nodes["Background"].inputs[0].default_value = (0.035, 0.055, 0.09, 1)
scene.world.node_tree.nodes["Background"].inputs[1].default_value = 0.45

bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, -0.04))
floor = bpy.context.object
floor.name = "Studio Floor"
material = bpy.data.materials.new("Neutral studio floor")
material.diffuse_color = (0.16, 0.19, 0.23, 1)
floor.data.materials.append(material)

def add_area(name, location, energy, size, color):
    light_data = bpy.data.lights.new(name, "AREA")
    light_data.energy, light_data.shape, light_data.size = energy, "DISK", size
    light_data.color = color
    light = bpy.data.objects.new(name, light_data)
    scene.collection.objects.link(light)
    light.location = location
    light.rotation_euler = (Vector((0, 0, 1.1)) - light.location).to_track_quat("-Z", "Y").to_euler()

add_area("Key Softbox", (4, -4, 7), 1500, 5, (1.0, 0.82, 0.68))
add_area("Fill Softbox", (-4, -2, 4), 900, 4, (0.65, 0.78, 1.0))
add_area("Rim Light", (1, 4, 5), 1800, 3, (1.0, 0.9, 0.72))

camera_data = bpy.data.cameras.new("Cinematic Camera")
camera = bpy.data.objects.new("Cinematic Camera", camera_data)
scene.collection.objects.link(camera)
if scene.render.resolution_y > scene.render.resolution_x:
    camera.location = (0, -5.8, 2.8)
    camera_data.lens = 42
else:
    camera.location = (0, -8.5, 3.0)
    camera_data.lens = 52
camera.rotation_euler = (Vector((0, 0, 1.15)) - camera.location).to_track_quat("-Z", "Y").to_euler()
scene.camera = camera

assets = shot.get("assets", {})
wanted = shot.get("character_names") or list(assets.keys())
roots = []
for slot, name in enumerate(wanted[:4]):
    model_path = assets.get(name)
    if not model_path or not os.path.isfile(model_path):
        continue
    before = set(bpy.data.objects)
    if model_path.lower().endswith(".fbx"):
        bpy.ops.import_scene.fbx(filepath=model_path)
    else:
        bpy.ops.import_scene.gltf(filepath=model_path)
    imported = [obj for obj in bpy.data.objects if obj not in before]
    if not imported:
        continue
    root = bpy.data.objects.new("CharacterRoot_" + str(slot), None)
    scene.collection.objects.link(root)
    for obj in imported:
        world_matrix = obj.matrix_world.copy()
        obj.parent = root
        obj.matrix_world = world_matrix
    points = [obj.matrix_world @ Vector(corner) for obj in imported for corner in obj.bound_box]
    if points:
        min_z = min(point.z for point in points)
        max_z = max(point.z for point in points)
        span_x = max(point.x for point in points) - min(point.x for point in points)
        span_y = max(point.y for point in points) - min(point.y for point in points)
        max_dim = max(span_x, span_y, max_z - min_z, 0.001)
        root.scale = (2.6 / max_dim,) * 3
        root.location = (-0.55 + slot * 1.1, 0, 0)
    roots.append(root)

for root in roots:
    start_x = root.location.x - 0.18
    end_x = root.location.x + 0.18
    root.location.x = start_x
    root.keyframe_insert(data_path="location", frame=1)
    root.location.x = end_x
    root.keyframe_insert(data_path="location", frame=scene.frame_end)
camera.location.x = -0.12
camera.keyframe_insert(data_path="location", frame=1)
camera.location.x = 0.12
camera.keyframe_insert(data_path="location", frame=scene.frame_end)
scene.frame_set(1)
bpy.ops.render.render(animation=True)
