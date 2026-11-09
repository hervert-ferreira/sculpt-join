# SPDX-License-Identifier: GPL-3.0-or-later
"""
Sculpt Join

Join all visible meshes into a single object to sculpt or pose them together,
then apply the result back to each original object.

How it works:
  * The original objects are never destroyed. The add-on joins COPIES of them
    and only hides the originals.
  * Every vertex of every copy gets an id. "Apply to Originals" finds each
    vertex again by its id and writes only its new position back into the
    original mesh. Everything else stays exactly as it was: name, mesh data,
    materials, UVs, normals, attributes, Face Sets, modifiers (Multires
    included), parent, collections, constraints and animation.
  * So the topology must not change while joined: Dyntopo is switched off
    and a red warning appears if a remesh or similar changes it (Ctrl+Z).
  * Meshes with Multires join through their base mesh.
  * Dense meshes (no Multires): when the scene is heavier than the Face
    Limit, the limit is shared by surface area and each mesh that is too
    dense for its share joins as a light proxy with even faces (voxel remesh;
    open meshes get their holes closed for it). On Apply, the pose of each
    proxy is carried to every vertex of its dense original, details included.
    For fine detail, turn Dense Proxies off.
  * Meshes with Mirror modifiers join as one half (the copies have no
    modifiers). On Join, the add-on asks whether to apply those Mirror
    modifiers permanently, so both halves join. The copies are made from the
    mirrored shape and the originals only change once the join has
    succeeded, so Esc or a failed join leave them untouched.
  * If the joined mesh is deleted by accident, the panel offers to show the
    hidden originals again (the join table is also kept on the scene).
  * The originals are found again by a tag, not only by name, so renaming
    one while joined is fine. The tag is removed on Apply or Cancel.
  * The panel stays visible in every mode while a join is in progress.
  * Objects without materials get a temporary placeholder material while
    joined (so they do not show the material of another object).
  * Join and Apply show a progress bar in the middle of the viewport and can
    be cancelled with Esc (nothing is changed when cancelled).
  * The copies and the joined mesh live in an orange temporary collection,
    removed together with them.
  * The panel settings are saved with the .blend file.
  * Meshes with a negative scale (or a different sign than the active mesh)
    join with correct normals: Blender's join would turn them inside out, so
    their copies get their faces flipped first. The originals are not touched.
  * Before joining, meshes with deforming modifiers (Armature, Lattice...)
    are reported: they show their base shape while joined (Armature: rest
    pose). The modifiers stay on the originals and work again after Apply.

Known limitations:
  * Dyntopo, remesh or anything that adds or removes vertices cannot be
    applied: undo it (Ctrl+Z) or Cancel Join.
  * Meshes that share their mesh data with another object (Alt+D) cannot be
    joined.
  * With Dense Proxies and a low Face Limit, very thin pieces (fringes,
    cords) can vanish from their proxy and deform on Apply. Raise the Face
    Limit or leave them out of the join.
  * Brushes on a proxy act on everything the proxy can represent; only
    detail smaller than a proxy face is protected.
"""

import json
import os
import time
import uuid

import bpy

DATA_KEY = "sculpt_join_data"   # custom property stored on the joined object
BACKUP_KEY = "sculpt_join_backup"  # copy of that table on the scene (recovery)
ORIGINAL_KEY = "sj_original"    # temporary tag on each original while joined
COPY_PREFIX = "__SJ_copy_"      # prefix of the temporary copies
JOINED_NAME = "SculptJoin"      # name of the joined object while sculpting
# Modifiers that move vertices: while joined the copies have none, so the
# mesh shows its base shape (Armature: rest pose). Reported before joining.
DEFORM_MODIFIERS = {
    'ARMATURE', 'CAST', 'CORRECTIVE_SMOOTH', 'CURVE', 'DISPLACE', 'HOOK',
    'LAPLACIANDEFORM', 'LAPLACIANSMOOTH', 'LATTICE', 'MESH_DEFORM',
    'SHRINKWRAP', 'SIMPLE_DEFORM', 'SMOOTH', 'SURFACE_DEFORM', 'WARP', 'WAVE',
    'NODES', 'MESH_CACHE', 'MESH_SEQUENCE_CACHE', 'VOLUME_DISPLACE',
}
FACE_SET_ATTRIBUTE = ".sculpt_face_set"  # where Blender stores Face Sets
DEFAULT_FACE_SET = 1    # id of a mesh that has no Face Sets of its own
NO_FACE_SETS_TAG = "sj_no_face_sets"     # temporary face tag used while joining
PLACEHOLDER_MATERIAL = "__SJ_no_material__"  # temporary, for objects without material
VERTEX_ID_ATTRIBUTE = "sj_vertex_id"     # unique id of every vertex
TEMP_COLLECTION = "Sculpt Join (temporary)"  # holds the copies and the joined mesh
REST_PREFIX = "__SJ_rest_"              # rest shape of a dense-mesh proxy
PROXY_MIN_FACES = 1000                  # no proxy gets fewer faces than this
STEP_VERTICES = 25_000                  # progress update every this many vertices
PROXY_WORTH = 0.85                      # proxy only if it saves more than 15% of the faces


def _read_version():
    """Version string from blender_manifest.toml ('' if it cannot be read)."""
    try:
        import tomllib
        path = os.path.join(os.path.dirname(__file__), "blender_manifest.toml")
        with open(path, "rb") as manifest:
            return tomllib.load(manifest)["version"]
    except Exception:
        return ""


VERSION = _read_version()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_info(obj):
    """Read the table stored on the joined object (None if it is not a join)."""
    if obj is None:
        return None
    raw = obj.get(DATA_KEY)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _find_joined():
    """The joined object of the join in progress (None if there is none).
    An object that is in no scene any more (unlinked) does not count."""
    for obj in bpy.data.objects:
        if DATA_KEY in obj.keys() and _get_info(obj) is not None and obj.users_scene:
            return obj
    return None


def _clear_backup():
    """Remove the copy of the join table from every scene."""
    for scene in bpy.data.scenes:
        if BACKUP_KEY in scene.keys():
            del scene[BACKUP_KEY]


def _lost_info(scene):
    """The join table of a join whose joined mesh is gone (None otherwise)."""
    if scene is None or scene.get(BACKUP_KEY) is None or _find_joined() is not None:
        return None
    try:
        info = json.loads(scene[BACKUP_KEY])
    except (ValueError, TypeError):
        return None
    return info if isinstance(info, dict) and info.get("entries") else None


def _find_original(entry):
    """The original object of an entry: by its tag, so a rename does not lose it."""
    obj = bpy.data.objects.get(entry["name"])
    uid = entry["uid"]
    if obj is not None and obj.get(ORIGINAL_KEY) == uid:
        return obj
    for other in bpy.data.objects:
        if other.get(ORIGINAL_KEY) == uid and DATA_KEY not in other.keys():
            return other
    return None


def _release_originals(info):
    """Remove the temporary tag from the originals."""
    for entry in info.get("entries", []):
        orig = _find_original(entry)
        if orig is not None and ORIGINAL_KEY in orig.keys():
            del orig[ORIGINAL_KEY]


def _leave_mode(context):
    """Back to Object Mode (from Sculpt, Edit... on whatever object is active)."""
    if context.mode != 'OBJECT' and context.active_object is not None:
        bpy.ops.object.mode_set(mode='OBJECT')


def _meshes(count):
    """'1 mesh' / '6 meshes'."""
    return f"{count} mesh" if count == 1 else f"{count} meshes"


def _deselect_all(context):
    for obj in context.view_layer.objects:
        obj.select_set(False)


def _activate(context, obj):
    """Make obj the only selected and active object."""
    try:
        obj.hide_set(False)
    except RuntimeError:
        pass
    _deselect_all(context)
    context.view_layer.objects.active = obj
    obj.select_set(True)


def _focus(context, joined):
    """Object Mode with the joined object active (from any mode, any object)."""
    _leave_mode(context)
    if context.active_object != joined:
        _activate(context, joined)


def _view_locator(context):
    """Where the 3D viewport of the operator is: {screen name, area index}."""
    area, screen = context.area, context.screen
    if area is None or screen is None or area.type != 'VIEW_3D':
        return None
    for index, other in enumerate(screen.areas):
        if other == area:
            return {"screen": screen.name, "area": index}
    return None


def _space_at(locator):
    """The 3D viewport space of a locator (None if that viewport is gone)."""
    if not locator:
        return None
    screen = bpy.data.screens.get(locator.get("screen", ""))
    index = locator.get("area", -1)
    if screen is None or not 0 <= index < len(screen.areas):
        return None
    area = screen.areas[index]
    if area.type != 'VIEW_3D':
        return None
    return area.spaces.active


def _join_space(info):
    """The viewport whose shading and Statistics the join changed."""
    return _space_at(info.get("view"))


def _restore_view(context, info):
    """Give the joining viewport its color type and Statistics back, unless the
    user changed them meanwhile."""
    space = _join_space(info)
    if space is None:
        return
    old = info.get("shading_color_type")
    if old and space.shading.color_type == 'SINGLE':
        space.shading.color_type = old
    if info.get("stats_was_on") is False and space.overlay.show_stats:
        space.overlay.show_stats = False


def _set_face_set(mesh, value):
    """Give every face of the mesh the same Face Set id (silently fails)."""
    try:
        attr = mesh.attributes.get(FACE_SET_ATTRIBUTE)
        if attr is None:
            attr = mesh.attributes.new(FACE_SET_ATTRIBUTE, 'INT', 'FACE')
        attr.data.foreach_set("value", [value] * len(attr.data))
    except (RuntimeError, TypeError, ValueError, KeyError, AttributeError):
        pass


def _has_real_face_sets(mesh):
    """True if the mesh has Face Sets of its own (any id other than the default)."""
    attr = mesh.attributes.get(FACE_SET_ATTRIBUTE)
    if attr is None:
        return False
    values = [0] * len(attr.data)
    attr.data.foreach_get("value", values)
    return any(v != DEFAULT_FACE_SET for v in values)


def _drop_face_set_attribute(mesh):
    """Remove the Face Set attribute (only used when it holds nothing but the default id)."""
    attr = mesh.attributes.get(FACE_SET_ATTRIBUTE)
    if attr is not None:
        try:
            mesh.attributes.remove(attr)
        except (RuntimeError, TypeError):
            pass


def _tag_faces(mesh, name, value):
    """Fill a temporary integer face attribute with one value (silently fails)."""
    try:
        attr = mesh.attributes.get(name)
        if attr is None:
            attr = mesh.attributes.new(name, 'INT', 'FACE')
        attr.data.foreach_set("value", [value] * len(attr.data))
    except (RuntimeError, TypeError, ValueError, KeyError, AttributeError):
        pass


def _normalize_face_sets(mesh):
    """
    Face Sets = None must join the meshes as they are. When only some of them
    have Face Sets, Blender's join gives every mesh WITHOUT Face Sets a new id
    of its own, which makes each one look like a Face Set. Put the faces of
    those meshes (tagged before the join) back to the default id.
    """
    try:
        tag = mesh.attributes.get(NO_FACE_SETS_TAG)
        face_set = mesh.attributes.get(FACE_SET_ATTRIBUTE)
        if tag is not None and face_set is not None:
            count = len(face_set.data)
            tags = [0] * count
            values = [0] * count
            tag.data.foreach_get("value", tags)
            face_set.data.foreach_get("value", values)
            values = [DEFAULT_FACE_SET if t else v for t, v in zip(tags, values)]
            face_set.data.foreach_set("value", values)
    except (RuntimeError, TypeError, ValueError, KeyError, AttributeError):
        pass
    finally:
        tag = mesh.attributes.get(NO_FACE_SETS_TAG)
        if tag is not None:
            mesh.attributes.remove(tag)


def _face_sets_per_mesh_ok(obj, expected):
    """True if the joined mesh carries exactly `expected` different Face Sets."""
    attr = obj.data.attributes.get(FACE_SET_ATTRIBUTE)
    if attr is None or attr.domain != 'FACE':
        return False
    values = [0] * len(attr.data)
    attr.data.foreach_get("value", values)
    # Ids start at 1, so a 0 means some mesh did not carry its Face Set.
    return 0 not in values and len(set(values)) == expected


def _mirror_modifiers(obj):
    """Names of the enabled Mirror modifiers that can be applied to obj."""
    if any(m.type == 'MULTIRES' for m in obj.modifiers):
        return []       # Blender does not apply modifiers on Multires meshes
    return [m.name for m in obj.modifiers if m.type == 'MIRROR' and m.show_viewport]


def _mirror_after_others(obj):
    """True if a Mirror to apply comes after another enabled modifier. It is
    then applied on the base mesh, before them (as Blender's own Apply does),
    and the final shape can differ a little."""
    seen_other = False
    for mod in obj.modifiers:
        if not mod.show_viewport:
            continue
        if mod.type == 'MIRROR':
            if seen_other:
                return True
        else:
            seen_other = True
    return False


def _deform_modifiers(obj):
    """Names of the enabled modifiers of obj that change its shape in the
    viewport (not shown while joined)."""
    return [m.name for m in obj.modifiers
            if m.type in DEFORM_MODIFIERS and m.show_viewport]


def _flips(obj, active):
    """True if obj's scale has another sign than the active mesh's. Blender's
    join would then turn obj inside out inside the joined mesh."""
    return ((obj.matrix_world.determinant() < 0)
            != (active.matrix_world.determinant() < 0))


def _flip_faces(mesh):
    """Reverse the winding of every face. Vertex order stays the same, so the
    vertex ids (and the Apply) are not affected."""
    import bmesh
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()


def _deform_note_objects(context, eligible):
    """Meshes to report for their deforming modifiers (none if turned off)."""
    if not context.scene.sculpt_join_warn_deform:
        return []
    return [o for o in eligible if _deform_modifiers(o)]


def _mirrored_mesh(context, obj):
    """
    New mesh = the mesh of obj with its enabled Mirror modifiers applied, in
    stack order (the same result as Apply on each of them). obj is not changed.
    """
    names = _mirror_modifiers(obj)
    tmp = obj.copy()
    tmp.data = obj.data.copy()
    for mod in list(tmp.modifiers):
        if mod.name not in names:
            tmp.modifiers.remove(mod)
    context.scene.collection.objects.link(tmp)
    try:
        depsgraph = context.evaluated_depsgraph_get()
        mesh = bpy.data.meshes.new_from_object(
            tmp.evaluated_get(depsgraph), preserve_all_data_layers=True,
            depsgraph=depsgraph)
    finally:
        tmp_mesh = tmp.data
        bpy.data.objects.remove(tmp, do_unlink=True)
        if tmp_mesh.users == 0:
            bpy.data.meshes.remove(tmp_mesh)
    mesh.name = f"__SJ_mirrored_{obj.name}"
    return mesh


def _commit_mirror(obj, mirrored):
    """Make the Mirror permanent on the original: its mesh gets the mirrored
    geometry (same datablock, name and materials) and the Mirror modifiers go."""
    import bmesh
    names = _mirror_modifiers(obj)
    bm = bmesh.new()
    try:
        bm.from_mesh(mirrored)
        bm.to_mesh(obj.data)
    finally:
        bm.free()
    obj.data.update()
    for name in names:
        mod = obj.modifiers.get(name)
        if mod is not None:
            obj.modifiers.remove(mod)


def _skip_reason(obj):
    """Reason why an object cannot be joined (None if it can)."""
    me = obj.data
    if getattr(obj, "library", None) or getattr(me, "library", None):
        return "linked data"
    if len(me.vertices) == 0:
        return "no vertices"
    # Edges or points only (e.g. a Skin modifier skeleton): nothing to sculpt,
    # invisible while joined, and its Skin/Mirror data must not be touched.
    if len(me.polygons) == 0:
        return "no faces (edges or points only)"
    if me.shape_keys is not None:
        return "has Shape Keys"
    # The positions are written into the original mesh, so it cannot be shared.
    if me.users - (1 if me.use_fake_user else 0) > 1:
        return "shares its mesh data with another object"
    return None


def _collect_eligible(context, selected_only=False):
    """
    Visible meshes of the current view layer as (eligible, skipped).
    With selected_only, unselected objects are left out (the active object is
    always considered). `skipped` lists (name, reason) of objects that were
    considered but cannot be joined.
    """
    active = context.active_object
    eligible, skipped = [], []
    for obj in context.view_layer.objects:
        if obj.type != 'MESH' or not obj.visible_get():
            continue
        if _get_info(obj) is not None:      # never join the SculptJoin itself
            continue
        if selected_only and obj != active and not obj.select_get():
            continue
        reason = _skip_reason(obj)
        if reason:
            skipped.append((obj.name, reason))
        else:
            eligible.append(obj)
    return eligible, skipped


def _join_problem(active, eligible, skipped):
    """(report level, message) if the join cannot happen at all, else None."""
    if active not in eligible:
        reason = dict(skipped).get(active.name, "not eligible")
        return {'ERROR'}, f"The active mesh cannot be joined: {reason}."
    if len(eligible) < 2:
        return {'WARNING'}, ("At least 2 meshes are needed. Check visibility "
                             "and the selection.")
    return None


def _remove_placeholder():
    """Remove the temporary placeholder material once nothing uses it."""
    mat = bpy.data.materials.get(PLACEHOLDER_MATERIAL)
    if mat is not None and mat.users == 0:
        bpy.data.materials.remove(mat)


def _face_set_rule(mesh, face_set, no_face_sets):
    """Prepare the Face Sets of a copy (see the Face Sets option of the join)."""
    # One Face Set per mesh: the join carries this attribute to the joined mesh.
    if face_set is not None:
        _set_face_set(mesh, face_set)
    # Face Sets = None with a mix of meshes: mark the faces of the meshes that
    # have no Face Sets, so they can be put back to the default id after the join.
    elif no_face_sets == 'TAG':
        _tag_faces(mesh, NO_FACE_SETS_TAG, 1)
    # Face Sets = None and no mesh has real Face Sets: any attribute only holds
    # the default id, and the join would still give each mesh an id of its own.
    elif no_face_sets == 'DROP':
        _drop_face_set_attribute(mesh)


def _tag_vertex_ids(mesh, offset):
    """Give every vertex a unique id (offset + its index)."""
    attr = mesh.attributes.get(VERTEX_ID_ATTRIBUTE)
    if attr is None:
        attr = mesh.attributes.new(VERTEX_ID_ATTRIBUTE, 'INT', 'POINT')
    attr.data.foreach_set("value", list(range(offset, offset + len(attr.data))))


def _make_copy(context, obj, index, placeholder, face_set=None,
               no_face_sets=None, mesh=None, flip=False):
    """Create a clean copy of the object for the join (`mesh`: use this shape
    instead of the object's own mesh, e.g. its mirrored version; `flip`:
    reverse its faces, see _flips)."""
    world = obj.matrix_world.copy()

    dup = obj.copy()
    dup.data = (mesh or obj.data).copy()
    dup.name = f"{COPY_PREFIX}{index}"

    # Without any material, the faces would take slot 0 of the joined object
    # and show another object's material. Give them a neutral placeholder.
    if all(m is None for m in dup.data.materials):
        dup.data.materials.clear()
        dup.data.materials.append(placeholder)

    _face_set_rule(dup.data, face_set, no_face_sets)
    if flip:
        _flip_faces(dup.data)

    # Nothing that could interfere with the join or the position.
    dup.modifiers.clear()
    for con in list(dup.constraints):
        dup.constraints.remove(con)
    dup.animation_data_clear()
    dup.parent = None
    dup.matrix_world = world
    dup.hide_select = False

    _temp_collection(context).objects.link(dup)

    return dup


def _copy_face_sets(src_mesh, mesh):
    """Copy the Face Sets of a mesh to a copy with the same faces in the same order."""
    try:
        attr = src_mesh.attributes.get(FACE_SET_ATTRIBUTE)
        if attr is None or len(attr.data) != len(mesh.polygons):
            return
        values = [0] * len(attr.data)
        attr.data.foreach_get("value", values)
        copy = mesh.attributes.new(FACE_SET_ATTRIBUTE, 'INT', 'FACE')
        copy.data.foreach_set("value", values)
    except (RuntimeError, TypeError, ValueError, KeyError, AttributeError):
        pass


def _make_proxy(context, obj, index, placeholder, face_set=None, no_face_sets=None,
                flip=False):
    """
    Meshes with Multires: a copy made of the base geometry only.
    The displacement data stays on the original, which is never touched.
    """
    src = obj.data
    mesh = bpy.data.meshes.new(f"{COPY_PREFIX}{index}")
    mesh.from_pydata([tuple(v.co) for v in src.vertices], [],
                     [tuple(p.vertices) for p in src.polygons], shade_flat=False)
    mesh.update()
    mesh.materials.append(placeholder)
    # The proxy must look like the original: keep its Face Sets, otherwise the
    # join would give this mesh a Face Set of its own.
    _copy_face_sets(src, mesh)
    _face_set_rule(mesh, face_set, no_face_sets)
    if flip:
        _flip_faces(mesh)

    dup = bpy.data.objects.new(f"{COPY_PREFIX}{index}", mesh)
    dup.matrix_world = obj.matrix_world.copy()
    _temp_collection(context).objects.link(dup)
    return dup


def _temp_collection(context):
    """Orange collection that holds the copies and the joined mesh while joined."""
    coll = bpy.data.collections.get(TEMP_COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(TEMP_COLLECTION)
        coll.color_tag = 'COLOR_02'
    if coll.name not in context.scene.collection.children:
        context.scene.collection.children.link(coll)
    return coll


def _drop_temp_collection():
    """Remove the temporary collection. Anything still in it moves to the scene."""
    coll = bpy.data.collections.get(TEMP_COLLECTION)
    if coll is None:
        return
    scene = bpy.context.scene
    for obj in list(coll.objects):
        if len(obj.users_collection) == 1:
            scene.collection.objects.link(obj)
        coll.objects.unlink(obj)
    bpy.data.collections.remove(coll)


def _drop_copies(objects, meshes):
    """Remove copies (and orphan meshes). Used for rollback and cleanup."""
    for obj in objects:
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except (ReferenceError, RuntimeError):
            pass
    for mesh in meshes:
        try:
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        except (ReferenceError, RuntimeError):
            pass


def _show_originals(info):
    """Unhide the original objects and return them."""
    shown = []
    for entry in info["entries"]:
        orig = _find_original(entry)
        if orig is None:
            continue
        try:
            orig.hide_set(False)
        except RuntimeError:
            pass
        shown.append(orig)
    return shown


def _discard_joined(context, joined, info, sculpt=True, restore_selection=False):
    """Remove the joined mesh and give the scene back to the originals.
    Call in Object Mode. `sculpt`: end in Sculpt Mode on the old active object.
    `restore_selection`: select again what was selected before the join."""
    mesh = joined.data
    bpy.data.objects.remove(joined, do_unlink=True)
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh)
    _drop_rest_meshes(info)     # first: the rest shapes may use the placeholder
    _remove_placeholder()
    _drop_temp_collection()
    originals = _show_originals(info)
    _enter_sculpt(context, info, originals, sculpt)
    if restore_selection:
        _restore_selection(context, info)
    _release_originals(info)
    _restore_view(context, info)
    _clear_backup()


def _enter_sculpt(context, info, candidates, sculpt=True):
    """Re-activate the object that was active before the join (in Sculpt Mode
    if `sculpt`)."""
    target = None
    index = info["active_index"]
    if 0 <= index < len(info["entries"]):
        target = _find_original(info["entries"][index])
    if target is None:
        target = bpy.data.objects.get(info.get("active", ""))
    if target is None and candidates:
        target = candidates[0]
    if target is None or target.name not in context.view_layer.objects:
        return
    _deselect_all(context)
    context.view_layer.objects.active = target
    target.select_set(True)
    if sculpt:
        bpy.ops.object.mode_set(mode='SCULPT')


def _restore_selection(context, info):
    """Select again what was selected before the join (originals by their tag,
    other objects by name). The active object stays as it is."""
    in_layer = context.view_layer.objects
    objects = [_find_original(info["entries"][i]) for i in info.get("selected", [])
               if 0 <= i < len(info["entries"])]
    objects += [in_layer.get(name) for name in info.get("selected_other", [])]
    for obj in objects:
        if obj is not None and obj.name in in_layer:
            try:
                obj.select_set(True)
            except RuntimeError:        # hidden or not selectable: skip it
                pass


def _vertex_ids_ok(obj, expected):
    """True if the joined mesh carries exactly the ids 0..expected-1, once each."""
    import numpy as np
    attr = obj.data.attributes.get(VERTEX_ID_ATTRIBUTE)
    if attr is None or len(attr.data) != expected:
        return False
    ids = np.empty(expected, dtype='int32')
    attr.data.foreach_get("value", ids)
    return len(np.unique(ids)) == expected and int(ids.min()) == 0 and int(ids.max()) == expected - 1


def _to_world(coords, matrix):
    """Transform an (N, 3) array of points by a 4x4 matrix."""
    return coords.astype('float64') @ matrix[:3, :3].T + matrix[:3, 3]


def _positions_for(world, ids, offset, count, inverse):
    """
    Local positions of one original: the `count` vertices whose ids start at
    `offset`, in the original's own order. None if any vertex is missing.
    """
    import numpy as np
    mask = (ids >= offset) & (ids < offset + count)
    if int(mask.sum()) != count:
        return None
    order = ids[mask] - offset
    if len(np.unique(order)) != count:
        return None
    out = np.empty((count, 3), dtype='float32')
    out[order] = _to_world(world[mask], inverse)
    return out


def _write_positions(joined, entries):
    """
    Write the vertex positions of the joined mesh to the originals.
    Generator: yields (fraction, text) and returns (updated, problems).
    Nothing is written before the last step, so stopping early changes nothing.
    """
    import numpy as np
    mesh = joined.data
    count = len(mesh.vertices)
    ids_attr = mesh.attributes.get(VERTEX_ID_ATTRIBUTE)
    if ids_attr is None or count != sum(e["n"] for e in entries):
        raise ValueError("the joined mesh changed (Dyntopo, remesh or deleted "
                         "geometry). The join needs the same vertices: undo "
                         "with Ctrl+Z, or Cancel Join")

    coords = np.empty(count * 3, dtype='float32')
    mesh.vertices.foreach_get("co", coords)
    ids = np.empty(count, dtype='int32')
    ids_attr.data.foreach_get("value", ids)
    world = _to_world(coords.reshape(-1, 3), np.array(joined.matrix_world))

    work = [e.get("dense_n", e["n"]) * (20 if "rest" in e else 1) for e in entries]
    total, done = float(sum(work)) or 1.0, 0.0
    updates, problems = [], []
    for entry, cost in zip(entries, work):
        orig = _find_original(entry)
        label = orig.name if orig is not None else entry["name"]
        yield done / total, f"Applying {label}"
        expected = entry.get("dense_n", entry["n"])
        if orig is None:
            problems.append(f"{label}: original missing (left as is)")
            continue
        if orig.type != 'MESH' or len(orig.data.vertices) != expected:
            problems.append(f"{label}: original changed (left as is)")
            continue
        inverse = np.array(orig.matrix_world.inverted_safe())
        local = _positions_for(world, ids, entry["off"], entry["n"], inverse)
        if local is None:
            problems.append(f"{label}: vertices missing (left as is)")
            continue
        if "rest" in entry:     # proxy: carry its pose to the dense original
            steps = _dense_positions(orig, entry, local.astype('float64'))
            try:
                while True:
                    part = next(steps)
                    yield (done + part * cost) / total, f"Carrying pose to {label}"
            except StopIteration as stop:
                local = stop.value
            if local is None:
                problems.append(f"{label}: proxy rest shape missing (left as is)")
                continue
        updates.append((orig, local))
        done += cost

    yield 1.0, "Writing"
    for orig, local in updates:     # only after everything was checked
        orig.data.vertices.foreach_set("co", local.ravel())
        orig.data.update()
    return len(updates), problems


# ---------------------------------------------------------------------------
# Proxies for dense meshes
# ---------------------------------------------------------------------------

def _face_count(mesh):
    """Number of faces, as the viewport Statistics count them."""
    return len(mesh.polygons)


def _tri_count(mesh):
    """Number of triangles of a mesh (an n-gon counts n - 2)."""
    import numpy as np
    totals = np.empty(len(mesh.polygons), dtype='int32')
    mesh.polygons.foreach_get("loop_total", totals)
    return int((totals - 2).sum())


def _world_area(obj, mesh=None):
    """Surface area of the mesh in world units (scale taken into account)."""
    mesh = mesh or obj.data
    det = abs(obj.matrix_world.to_3x3().determinant())
    return _mesh_area(mesh) * (det ** (2.0 / 3.0) if det > 0 else 1.0)


# foreach_get is only fast when the array has Blender's own type (float32 for
# positions and areas, int32 for indices); any other type copies item by item.

def _read_co(mesh):
    """Vertex positions (N, 3) float64, read the fast way."""
    import numpy as np
    co = np.empty(len(mesh.vertices) * 3, dtype='float32')
    mesh.vertices.foreach_get("co", co)
    return co.reshape(-1, 3).astype('float64')


def _corner_edges(mesh):
    """Edge index of every face corner (the internal attribute is ~40x faster
    to read than loops.edge_index)."""
    import numpy as np
    out = np.empty(len(mesh.loops), dtype='int32')
    attr = mesh.attributes.get(".corner_edge")
    if attr is not None and attr.domain == 'CORNER' and attr.data_type == 'INT':
        attr.data.foreach_get("value", out)
    else:
        mesh.loops.foreach_get("edge_index", out)
    return out


def _edge_use(mesh):
    """Number of faces using each edge."""
    import numpy as np
    return np.bincount(_corner_edges(mesh), minlength=len(mesh.edges))


def _is_closed(mesh):
    """True if every edge has exactly two faces (a watertight surface)."""
    if len(mesh.edges) == 0 or len(mesh.loops) == 0:
        return False
    if len(mesh.loops) != 2 * len(mesh.edges):    # can't be: answer at once
        return False
    return bool((_edge_use(mesh) == 2).all())


def _has_multires(obj):
    return any(m.type == 'MULTIRES' for m in obj.modifiers)


def _plan_proxies(objects, budget, mesh_of=lambda obj: obj.data):
    """
    Share the face budget by surface area. Returns {name: target faces}
    for the meshes that should join as a proxy (the others join as they are).
    `mesh_of(obj)` is the shape that joins (e.g. the mirrored one).

    Pieces that already fit in their share keep full resolution and give the
    rest back to the others, so a small dense ring is reduced while a big
    light armor is left alone. Multires meshes join by their base mesh and
    only use up budget.
    """
    faces, area = {}, {}
    remaining = budget
    for obj in objects:
        mesh = mesh_of(obj)
        n = _face_count(mesh)
        if _has_multires(obj):
            remaining -= n
            continue
        faces[obj.name] = n
        area[obj.name] = max(_world_area(obj, mesh), 1e-12)
    if sum(faces.values()) <= remaining:
        return {}

    active = set(faces)
    while active:
        total = sum(area[n] for n in active)
        share = {n: max(PROXY_MIN_FACES, max(remaining, 0) * area[n] / total) for n in active}
        fits = [n for n in active if faces[n] <= share[n]]
        if not fits:
            break
        for n in fits:
            remaining -= faces[n]
            active.discard(n)

    plan = {}
    total = sum(area[n] for n in active) or 1.0
    for n in active:
        target = int(max(PROXY_MIN_FACES, max(remaining, 0) * area[n] / total))
        if target <= faces[n] * PROXY_WORTH:
            plan[n] = target
    return plan


def _evaluated_copy(context, mesh, modifiers):
    """
    New mesh = `mesh` with the given modifiers applied, in the mesh's own space.
    `modifiers` is a list of (type, {property: value}).
    """
    tmp_mesh = mesh.copy()
    tmp = bpy.data.objects.new("__SJ_tmp__", tmp_mesh)
    context.scene.collection.objects.link(tmp)
    try:
        for kind, props in modifiers:
            mod = tmp.modifiers.new(kind.lower(), kind)
            for key, value in props.items():
                setattr(mod, key, value)
        depsgraph = context.evaluated_depsgraph_get()
        return bpy.data.meshes.new_from_object(tmp.evaluated_get(depsgraph))
    finally:
        bpy.data.objects.remove(tmp, do_unlink=True)
        bpy.data.meshes.remove(tmp_mesh)


def _bbox_size(mesh):
    import numpy as np
    co = np.empty(len(mesh.vertices) * 3, dtype='float32')
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    return co.max(0).astype('float64') - co.min(0)


def _same_size(src, proxy):
    """True if the proxy keeps the size of the mesh (no part vanished)."""
    import numpy as np
    if len(proxy.polygons) == 0:
        return False
    a, b = _bbox_size(src), _bbox_size(proxy)
    scale = float(a.max()) or 1.0
    return bool(np.all(np.abs(a - b) <= 0.08 * scale))


def _mesh_area(mesh):
    import numpy as np
    areas = np.empty(len(mesh.polygons), dtype='float32')
    mesh.polygons.foreach_get("area", areas)
    return float(areas.sum(dtype='float64'))


def _int_attribute(mesh, name, collection, prop, count, width=1):
    """Read an int array: the internal attribute if there is one (fast), else
    the classic property."""
    import numpy as np
    out = np.empty(count * width, dtype='int32')
    attr = mesh.attributes.get(name)
    if attr is not None and attr.data_type in ('INT', 'INT32_2D'):
        attr.data.foreach_get("value", out)
    else:
        collection.foreach_get(prop, out)
    return out.reshape(-1, width) if width > 1 else out


def _corner_verts(mesh):
    return _int_attribute(mesh, ".corner_vert", mesh.loops, "vertex_index", len(mesh.loops))


def _edge_verts(mesh):
    return _int_attribute(mesh, ".edge_verts", mesh.edges, "vertices", len(mesh.edges), 2)


def _face_starts(mesh):
    import numpy as np
    out = np.empty(len(mesh.polygons), dtype='int32')
    mesh.polygons.foreach_get("loop_start", out)
    return out


def _tree_of(context, mesh):
    """BVH tree of a mesh in its own space. Built in C from a temporary
    object: much faster than from Python lists of vertices and faces."""
    from mathutils.bvhtree import BVHTree
    tmp = bpy.data.objects.new("__SJ_tmp_tree__", mesh)
    context.scene.collection.objects.link(tmp)
    try:
        return BVHTree.FromObject(tmp, context.evaluated_depsgraph_get())
    finally:
        bpy.data.objects.remove(tmp, do_unlink=True)


def _lid_faces(mesh, use):
    """
    Faces that close the holes of an open mesh, as lists of its vertex
    indices. Only the faces along the holes go through bmesh, not the whole
    (possibly huge) mesh.
    """
    import bmesh
    import numpy as np
    boundary = np.flatnonzero(use == 1)
    if len(boundary) == 0:
        return []
    is_boundary = np.zeros(len(use), dtype=bool)
    is_boundary[boundary] = True
    corner_vert, starts = _corner_verts(mesh), _face_starts(mesh)
    ends = np.append(starts[1:], len(corner_vert))
    corners = np.flatnonzero(is_boundary[_corner_edges(mesh)])
    faces = np.unique(np.searchsorted(starts, corners, side='right') - 1)
    co = np.empty(len(mesh.vertices) * 3, dtype='float32')
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)

    bm = bmesh.new()
    try:
        bm_vert, original = {}, []
        def vert(i):
            v = bm_vert.get(i)
            if v is None:
                v = bm_vert[i] = bm.verts.new(co[i].tolist())
                original.append(i)
            return v
        for f in faces.tolist():
            try:
                bm.faces.new([vert(i) for i in corner_vert[starts[f]:ends[f]].tolist()])
            except ValueError:          # duplicate face: not needed for the lid
                pass
        bm.verts.index_update()
        edges = []
        for a, b in _edge_verts(mesh)[boundary].tolist():
            if a in bm_vert and b in bm_vert:
                edge = bm.edges.get((bm_vert[a], bm_vert[b]))
                if edge is not None:
                    edges.append(edge)
        before = set(bm.faces)
        bmesh.ops.holes_fill(bm, edges=edges, sides=0)
        return [[original[v.index] for v in f.verts] for f in bm.faces if f not in before]
    finally:
        bm.free()


def _closed_mesh(mesh, lids):
    """Temporary mesh = positions and faces of `mesh` plus the lid faces."""
    import numpy as np
    co = np.empty(len(mesh.vertices) * 3, dtype='float32')
    mesh.vertices.foreach_get("co", co)
    corner_vert, starts = _corner_verts(mesh), _face_starts(mesh)
    sizes = np.array([len(lid) for lid in lids], dtype='int32')
    lid_corners = np.fromiter((i for lid in lids for i in lid), dtype='int32',
                              count=int(sizes.sum()))
    corners = np.concatenate([corner_vert, lid_corners])
    lid_starts = len(corner_vert) + np.concatenate([[0], np.cumsum(sizes)[:-1]])
    all_starts = np.concatenate([starts, lid_starts]).astype('int32')

    closed = bpy.data.meshes.new("__SJ_tmp_closed__")
    closed.vertices.add(len(mesh.vertices))
    closed.vertices.foreach_set("co", co)
    closed.loops.add(len(corners))
    closed.polygons.add(len(all_starts))
    attr = closed.attributes.get(".corner_vert")
    if attr is not None and attr.data_type == 'INT':
        attr.data.foreach_set("value", corners)
    else:
        closed.loops.foreach_set("vertex_index", corners)
    closed.polygons.foreach_set("loop_start", all_starts)
    closed.update(calc_edges=True)
    return closed


def _voxel_fit(context, src, volume, target, finish=None):
    """
    Voxel remesh `volume` so the result has about `target` faces, and keeps
    the size of `src`. The face count of a voxel remesh depends on how the
    surface sits in the grid, so the voxel size is corrected from the first
    result. Parts thinner than a voxel vanish: then the voxel gets finer, even
    above the target. `finish(proxy, voxel)` can trim the result first.
    """
    import math
    voxel = math.sqrt(1.5 * _mesh_area(src) / target)
    best = None
    for _attempt in range(4):
        proxy = _evaluated_copy(context, volume, [('REMESH', {
            "mode": 'VOXEL', "voxel_size": voxel, "use_remove_disconnected": False})])
        if finish is not None:
            finish(proxy, voxel)
        faces = _face_count(proxy)
        if not _same_size(src, proxy):
            bpy.data.meshes.remove(proxy)
            voxel *= 0.6                        # something thin was lost
            continue
        if best is not None:
            bpy.data.meshes.remove(best)
        best = proxy
        if 0.6 * target <= faces <= 1.15 * target:
            break
        voxel *= math.sqrt(max(faces, 1) / target)
    return best


def _proxy_voxel(context, mesh, target):
    """Closed meshes: voxel remesh at the size that gives about `target` faces."""
    return _voxel_fit(context, mesh, mesh, target)


def _proxy_voxel_open(context, mesh, target):
    """
    Open meshes (clothes, capes): close the holes on a temporary copy, voxel
    remesh it, then delete the proxy faces that only exist because of those
    lids. What is left is an even proxy of the open surface.
    """
    import bmesh

    lids = _lid_faces(mesh, _edge_use(mesh))
    if not lids:
        return None
    tree = _tree_of(context, mesh)
    closed = _closed_mesh(mesh, lids)

    def drop_lids(proxy, voxel):
        bm = bmesh.new()
        bm.from_mesh(proxy)
        far = [f for f in bm.faces
               if tree.find_nearest(f.calc_center_median(), 0.9 * voxel)[0] is None]
        bmesh.ops.delete(bm, geom=far, context='FACES')
        loose = [v for v in bm.verts if not v.link_faces]
        bmesh.ops.delete(bm, geom=loose, context='VERTS')
        bm.to_mesh(proxy)
        bm.free()

    try:
        return _voxel_fit(context, mesh, closed, target, drop_lids)
    finally:
        bpy.data.meshes.remove(closed)


def _proxy_split(context, mesh, target):
    """
    Last resort: collapse decimation, then split long edges. Decimation alone
    leaves long slivers on smooth areas, and a joint cannot bend inside one
    triangle. Can end above the target.
    """
    import math
    import bmesh
    proxy = _evaluated_copy(context, mesh, [('DECIMATE', {
        "ratio": min(1.0, target / max(_tri_count(mesh), 1)),
        "use_collapse_triangulate": True})])
    bm = bmesh.new()
    bm.from_mesh(proxy)
    area = sum(f.calc_area() for f in bm.faces)
    longest = 1.5 * math.sqrt(4.0 * area / (math.sqrt(3.0) * target))
    for _ in range(8):
        edges = [e for e in bm.edges if e.calc_length() > longest]
        if not edges:
            break
        bmesh.ops.subdivide_edges(bm, edges=edges, cuts=1)
        bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 3])
    bm.to_mesh(proxy)
    bm.free()
    return proxy if len(proxy.polygons) else None


def _build_proxy_mesh(context, mesh, target):
    """Light proxy of a dense mesh, in the mesh's own space. Returns (mesh, method)."""
    if _is_closed(mesh):
        steps = [("voxel", _proxy_voxel)]
    else:
        steps = [("voxel, holes closed", _proxy_voxel_open)]
    steps += [("split", _proxy_split)]
    for name, build in steps:
        try:
            proxy = build(context, mesh, target)
        except (RuntimeError, ValueError, TypeError):
            proxy = None
        if proxy is not None:
            return proxy, name
    return None, None


def _make_dense_proxy(context, obj, index, proxy_mesh, placeholder,
                      face_set=None, no_face_sets=None, flip=False):
    """Object for the join made from a proxy mesh, plus its saved rest shape."""
    proxy_mesh.name = f"{COPY_PREFIX}{index}"
    proxy_mesh.materials.clear()
    first = next((m for m in obj.data.materials if m is not None), None)
    proxy_mesh.materials.append(first or placeholder)
    proxy_mesh.shade_smooth()
    _face_set_rule(proxy_mesh, face_set, no_face_sets)
    if flip:            # before the rest copy: rest and pose need the same winding
        _flip_faces(proxy_mesh)

    rest = proxy_mesh.copy()        # the shape the pose is measured from
    rest.name = f"{REST_PREFIX}{index}"
    rest.use_fake_user = True       # survives save and reload while joined

    dup = bpy.data.objects.new(f"{COPY_PREFIX}{index}", proxy_mesh)
    dup.matrix_world = obj.matrix_world.copy()
    _temp_collection(context).objects.link(dup)
    return dup, rest


def _drop_rest_meshes(info):
    """Remove the saved rest shapes of the proxies of a join."""
    for entry in info.get("entries", []):
        mesh = bpy.data.meshes.get(entry.get("rest", ""))
        if mesh is not None:
            mesh.use_fake_user = False
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)


def _mesh_arrays(mesh):
    """(vertex positions (N, 3) float64, triangles (T, 3) int)."""
    import numpy as np
    mesh.calc_loop_triangles()
    tris = np.empty(len(mesh.loop_triangles) * 3, dtype='int32')
    mesh.loop_triangles.foreach_get("vertices", tris)
    return _read_co(mesh), tris.reshape(-1, 3).astype('int64')


def _vertex_normals(verts, tris):
    """Area-weighted vertex normals of a triangle mesh (proxy sized: cheap)."""
    import numpy as np
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    face_n = np.cross(b - a, c - a)                     # area weighted
    vert_n = np.zeros_like(verts)
    for axis in range(3):
        vert_n[:, axis] = sum(np.bincount(tris[:, k], face_n[:, axis], len(verts))
                              for k in range(3))
    vert_n /= np.linalg.norm(vert_n, axis=1, keepdims=True) + 1e-30
    return vert_n


def _frames(verts, vert_n, corners, weights):
    """
    Frame at each bound point: the vertex normals of its triangle blended by
    the barycentric weights (smooth across edges) and one triangle edge made
    perpendicular to it. `corners`: (n, 3) vertex indices of each triangle.
    """
    import numpy as np
    n = sum(weights[:, k:k + 1] * vert_n[corners[:, k]] for k in range(3))
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-30
    e = verts[corners[:, 1]] - verts[corners[:, 0]]
    e -= (e * n).sum(1, keepdims=True) * n
    e /= np.linalg.norm(e, axis=1, keepdims=True) + 1e-30
    return e, np.cross(n, e), n


def _closest_weights(p, a, b, c):
    """
    Barycentric weights (n, 3) of the point of each triangle (a, b, c) closest
    to p, all (n, 3) arrays (Ericson, Real-Time Collision Detection 5.1.5).
    """
    import numpy as np
    ab, ac = b - a, c - a
    ap, bp, cp = p - a, p - b, p - c
    d1, d2 = (ab * ap).sum(1), (ac * ap).sum(1)
    d3, d4 = (ab * bp).sum(1), (ac * bp).sum(1)
    d5, d6 = (ab * cp).sum(1), (ac * cp).sum(1)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2

    def ratio(num, den):
        return num / np.where(np.abs(den) > 1e-30, den, 1e-30)

    w = np.empty((len(p), 3))
    # Inside the face (default), then the regions that win over it, from the
    # weakest to the strongest test (the reverse of Ericson's early returns).
    total = va + vb + vc
    v, s = ratio(vb, total), ratio(vc, total)
    w[:, 0], w[:, 1], w[:, 2] = 1.0 - v - s, v, s
    m = (va <= 0) & (d4 - d3 >= 0) & (d5 - d6 >= 0)                 # edge BC
    s = ratio(d4 - d3, (d4 - d3) + (d5 - d6))[m]
    w[m] = np.stack([np.zeros_like(s), 1.0 - s, s], 1)
    m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)                           # edge AC
    s = ratio(d2, d2 - d6)[m]
    w[m] = np.stack([1.0 - s, np.zeros_like(s), s], 1)
    m = (d6 >= 0) & (d5 <= d6)                                      # corner C
    w[m] = (0.0, 0.0, 1.0)
    m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)                           # edge AB
    s = ratio(d1, d1 - d3)[m]
    w[m] = np.stack([1.0 - s, s, np.zeros_like(s)], 1)
    m = (d3 >= 0) & (d4 <= d3)                                      # corner B
    w[m] = (0.0, 1.0, 0.0)
    m = (d1 <= 0) & (d2 <= 0)                                       # corner A
    w[m] = (1.0, 0.0, 0.0)
    return w


CARRY_CHUNK = 500_000       # vertices per numpy block when carrying a pose


def _carry_pose(dense, rest, posed, tris):
    """
    Move the dense vertices (N, 3) the way the proxy moved from `rest` to
    `posed`. Each dense vertex is tied to the nearest point of the rest proxy:
    its triangle, its place inside it and its offset in a local frame. All
    arrays in world space.

    Generator: yields the fraction done (0..1) every few thousand vertices
    and returns the new positions.
    """
    import numpy as np
    from mathutils.bvhtree import BVHTree

    # Sliver triangles have no stable normal: a tiny move would swing the
    # frame and the offsets with it. Leave them out.
    a, b, c = rest[tris[:, 0]], rest[tris[:, 1]], rest[tris[:, 2]]
    double_area = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    longest = np.maximum.reduce([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1),
                                 np.linalg.norm(a - c, axis=1)])
    good = double_area > 1e-3 * longest * longest      # rejects needle triangles
    if good.sum() >= max(1, len(tris) // 2):
        tris = tris[good]

    # 1) Nearest triangle of every dense vertex. The only per-vertex Python
    #    work, so it keeps nothing but the index; the point itself is found
    #    again below, in numpy.
    tree = BVHTree.FromPolygons(rest.tolist(), tris.tolist(), all_triangles=True)
    count = len(dense)
    tri = np.empty(count, dtype='int64')
    find = tree.find_nearest
    for start in range(0, count, STEP_VERTICES):
        part = dense[start:start + STEP_VERTICES].tolist()
        tri[start:start + len(part)] = [find(p)[2] for p in part]
        yield 0.85 * (start + len(part)) / count

    # 2) Bind to the rest proxy and rebuild on the posed one, block by block
    #    (smaller temporaries, and progress keeps moving).
    rest_n, posed_n = _vertex_normals(rest, tris), _vertex_normals(posed, tris)
    out = np.empty_like(dense)
    for start in range(0, count, CARRY_CHUNK):
        block = slice(start, start + CARRY_CHUNK)
        p, corners = dense[block], tris[tri[block]]
        weights = _closest_weights(p, *(rest[corners[:, k]] for k in range(3)))
        hit = sum(weights[:, k:k + 1] * rest[corners[:, k]] for k in range(3))
        e1, e2, n = _frames(rest, rest_n, corners, weights)
        offset = p - hit
        l1, l2, l3 = ((offset * e1).sum(1, keepdims=True), (offset * e2).sum(1, keepdims=True),
                      (offset * n).sum(1, keepdims=True))
        point = sum(weights[:, k:k + 1] * posed[corners[:, k]] for k in range(3))
        f1, f2, fn = _frames(posed, posed_n, corners, weights)
        out[block] = point + l1 * f1 + l2 * f2 + l3 * fn
        yield 0.85 + 0.15 * min(count, start + CARRY_CHUNK) / count
    return out


def _dense_positions(orig, entry, posed_local):
    """
    New local positions of a dense original from the pose of its proxy.
    Generator (see _carry_pose); returns None if the rest shape is missing.
    """
    import numpy as np
    rest_mesh = bpy.data.meshes.get(entry["rest"])
    if rest_mesh is None or len(rest_mesh.vertices) != entry["n"]:
        return None
    yield 0.0
    rest_local, tris = _mesh_arrays(rest_mesh)
    matrix = np.array(orig.matrix_world)
    dense_local = _read_co(orig.data)
    moved = yield from _carry_pose(_to_world(dense_local, matrix),
                        _to_world(rest_local, matrix),
                        _to_world(posed_local, matrix), tris)
    return _to_world(moved, np.linalg.inv(matrix)).astype('float32')


# ---------------------------------------------------------------------------
# Progress bar (status bar) and steps that can be cancelled with Esc
# ---------------------------------------------------------------------------

_PROGRESS = {}      # {"factor": 0..1, "text": str} while a Join/Apply is running


def _fmt_time(seconds):
    """'4.2 s' below a minute, '1 min 05 s' from a minute on."""
    if seconds < 59.95:
        return f"{seconds:.1f} s"
    minutes, rest = divmod(int(round(seconds)), 60)
    return f"{minutes} min {rest:02d} s"


def _redraw_views():
    wm = bpy.context.window_manager
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _set_progress(factor, text):
    """Update the floating bar. Redraws at most ~6 times a second (a redraw of
    the viewport costs time in heavy scenes)."""
    factor = max(0.0, min(1.0, float(factor)))
    changed = (int(factor * 100) != int(_PROGRESS.get("factor", -1) * 100)
               or text != _PROGRESS.get("text"))
    _PROGRESS.update(factor=factor, text=text)
    now = time.perf_counter()
    if changed and now - _PROGRESS.get("drawn", 0.0) >= 0.15:
        _PROGRESS["drawn"] = now
        _redraw_views()


def _clear_progress():
    _PROGRESS.clear()
    _redraw_views()


def _busy():
    return bool(_PROGRESS)


_OVERLAY = {"handle": None}
BAR_COLOR = (0.278, 0.447, 0.702, 1.0)  # Blender's default progress blue


def _bar_color():
    """Fill color of Blender's own progress bars, from the user's theme."""
    try:
        return tuple(bpy.context.preferences.themes[0].user_interface.wcol_progress.item)
    except Exception:
        return BAR_COLOR


def _rect(shader, x, y, w, h, color):
    from gpu_extras.batch import batch_for_shader
    batch = batch_for_shader(shader, 'TRIS',
                             {"pos": ((x, y), (x + w, y), (x + w, y + h), (x, y + h))},
                             indices=((0, 1, 2), (2, 3, 0)))
    shader.uniform_float("color", color)
    batch.draw(shader)


def _text(font, text, x, y, size, color, center=True):
    import blf
    blf.size(font, size)
    blf.color(font, *color)
    width = blf.dimensions(font, text)[0]
    blf.position(font, x - width / 2 if center else x, y, 0)
    blf.draw(font, text)


def _draw_warning(region, scale):
    """Red banner at the top of the viewport: the join can't be applied."""
    import gpu
    lines = ("Sculpt Join: topology changed, this join can't be applied",
             "Press Ctrl+Z to undo the remesh (or Cancel Join)")
    width, height = 470 * scale, 48 * scale
    x, y = (region.width - width) / 2, region.height - height - 60 * scale
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    _rect(shader, x, y, width, height, (0.55, 0.08, 0.08, 0.9))
    gpu.state.blend_set('NONE')
    _text(0, lines[0], region.width / 2, y + height - 20 * scale, 13 * scale, (1, 1, 1, 1))
    _text(0, lines[1], region.width / 2, y + 9 * scale, 11 * scale, (1, 0.85, 0.85, 1))


def _draw_overlay():
    """Floating progress bar in the middle of each 3D viewport while working."""
    if _GUARD["bad"] and not _PROGRESS:
        region = bpy.context.region
        if region is not None:
            _draw_warning(region, bpy.context.preferences.system.ui_scale)
        return
    if not _PROGRESS:
        return
    import gpu
    region = bpy.context.region
    if region is None:
        return
    scale = bpy.context.preferences.system.ui_scale
    width, bar_h, pad = 340 * scale, 16 * scale, 14 * scale
    cx, cy = region.width / 2, region.height / 2
    x, y = cx - width / 2, cy - bar_h / 2
    box_bottom = y - pad - 18 * scale
    box_top = y + bar_h + pad + 18 * scale

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    _rect(shader, x - pad, box_bottom, width + 2 * pad, box_top - box_bottom, (0.08, 0.08, 0.08, 0.88))
    _rect(shader, x, y, width, bar_h, (0.25, 0.25, 0.25, 1.0))
    _rect(shader, x, y, width * _PROGRESS["factor"], bar_h, _bar_color())
    gpu.state.blend_set('NONE')

    font = 0
    white, grey = (1, 1, 1, 1), (0.75, 0.75, 0.75, 1)
    _text(font, f"Sculpt Join: {_PROGRESS['text']}", cx, y + bar_h + 8 * scale, 13 * scale, white)
    _text(font, f"{int(_PROGRESS['factor'] * 100)}%", cx, y + 4 * scale, 11 * scale, white)
    _text(font, "Esc to cancel", cx, box_bottom + 7 * scale, 11 * scale, grey)


class _Steps:
    """
    Runs a generator of steps: each step yields (fraction, text) and the
    generator returns the operator result. In the interface it runs as a
    modal operator, one step per timer tick, so the status bar shows the
    progress and Esc stops it between steps. Without a window (scripts,
    background) it simply runs to the end.
    """

    def _start(self, context, steps):
        self._steps = steps
        self._timer = None
        if bpy.app.background or context.window is None:
            try:
                while True:
                    next(steps)
            except StopIteration as stop:
                return stop.value
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.01, window=context.window)
        wm.modal_handler_add(self)
        _set_progress(0.0, "Starting")
        return {'RUNNING_MODAL'}

    def _stop(self, context):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        _clear_progress()

    def modal(self, context, event):
        try:
            if event.type == 'ESC' and event.value == 'PRESS':
                self._steps.close()     # the generator rolls back (GeneratorExit)
                self._stop(context)
                self.report({'WARNING'}, self._cancel_message)
                return {'CANCELLED'}
            if event.type != 'TIMER':
                return {'RUNNING_MODAL'}    # block other input while working
            try:
                factor, text = next(self._steps)
            except StopIteration as stop:
                self._stop(context)
                return stop.value
            _set_progress(factor, text)
            return {'RUNNING_MODAL'}
        except Exception as exc:        # never leave the bar or the copies behind
            try:
                self._steps.close()
            except Exception:
                pass
            self._stop(context)
            self.report({'ERROR'}, f"Sculpt Join stopped: {exc}")
            return {'CANCELLED'}

    def cancel(self, context):          # e.g. the window was closed
        try:
            self._steps.close()
        finally:
            self._stop(context)


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class OBJECT_OT_sculpt_join_start(_Steps, bpy.types.Operator):
    """Join copies of all visible meshes into one mesh, to sculpt or pose them together. In Solid shading, the viewport color can be set to Single while joined"""
    bl_idname = "object.sculpt_join_start"
    bl_label = "Join Visible"
    bl_options = {'UNDO'}

    selected_only: bpy.props.BoolProperty(
        name="Selected Only",
        description="Join only the selected meshes (plus the active one)",
        default=False,
        options={'SKIP_SAVE', 'HIDDEN'},
    )
    apply_mirror: bpy.props.BoolProperty(
        name="Apply Mirror modifiers permanently",
        description=("Apply the Mirror modifiers of the originals, so both halves "
                     "join. The originals only change once the join succeeded "
                     "(Esc leaves them untouched); then the Mirror is gone "
                     "(Ctrl+Z undoes it). Off: only the real half joins"),
        default=False,
        options={'SKIP_SAVE'},
    )

    @classmethod
    def description(cls, context, properties):
        if properties.selected_only:
            return ("Join only the selected meshes (plus the active one). "
                    "Select the parts in the Outliner, or in Object Mode "
                    "before entering Sculpt Mode. Avoid Dyntopo and remesh "
                    "tools while joined")
        return ("Join copies of all visible meshes into one mesh, to sculpt "
                "or pose them together. In Solid shading, the viewport color "
                "can be set to Single while joined. Avoid Dyntopo and remesh "
                "tools while joined")

    @classmethod
    def poll(cls, context):
        obj = context.object
        return (context.mode == 'SCULPT' and obj is not None and not _busy()
                and obj.type == 'MESH' and _find_joined() is None)

    def invoke(self, context, event):
        eligible, skipped = _collect_eligible(context, self.selected_only)

        problem = _join_problem(context.active_object, eligible, skipped)
        if problem:
            self.report(*problem)
            return {'CANCELLED'}

        mirrors = [o for o in eligible if _mirror_modifiers(o)]
        deform = _deform_note_objects(context, eligible)
        if skipped or mirrors or deform:  # let the user decide instead of acting silently
            return context.window_manager.invoke_props_dialog(
                self, width=420, title="Before Joining",
                confirm_text="Join Remaining" if skipped else "Join")
        return self.execute(context)

    def draw(self, context):
        layout = self.layout
        eligible, skipped = _collect_eligible(context, self.selected_only)
        mirrors = [o for o in eligible if _mirror_modifiers(o)]
        deform = _deform_note_objects(context, eligible)

        if deform:
            rigged = any(o.modifiers[n].type == 'ARMATURE'
                         for o in deform for n in _deform_modifiers(o))
            layout.label(text=f"{_meshes(len(deform))} with deforming modifiers:", icon='INFO')
            for obj in deform[:5]:
                layout.label(text=f"{obj.name}: {', '.join(_deform_modifiers(obj))}")
            if len(deform) > 5:
                layout.label(text=f"... and {len(deform) - 5} more")
            layout.label(text="While joined they show their base shape"
                              + (" (Armature: rest pose)." if rigged else "."))
            layout.label(text="The modifiers stay and work again after Apply.")
            layout.prop(context.scene, "sculpt_join_warn_deform",
                        text="Keep warning about deforming modifiers")
            if skipped or mirrors:
                layout.separator()

        if skipped:
            layout.label(text="These meshes stay untouched in the scene:")
            for name, reason in skipped[:10]:
                layout.label(text=f"{name}: {reason}")
            if len(skipped) > 10:
                layout.label(text=f"... and {len(skipped) - 10} more")
        if mirrors:
            if skipped:
                layout.separator()
            layout.label(text=f"{_meshes(len(mirrors))} with Mirror modifiers:")
            for obj in mirrors[:5]:
                if _mirror_after_others(obj):
                    layout.label(text=f"{obj.name} (Mirror not first: the result can differ)",
                                 icon='ERROR')
                else:
                    layout.label(text=obj.name)
            if len(mirrors) > 5:
                layout.label(text=f"... and {len(mirrors) - 5} more")
            layout.prop(self, "apply_mirror")
            layout.label(text="Off: only the real half of each mesh is joined.")

    _cancel_message = "Join cancelled (Esc). Nothing was changed."

    def execute(self, context):
        view = _view_locator(context)
        return self._start(context, self._join(context, view))

    def _join(self, context, view):
        """The join, as steps (see _Steps)."""
        active = context.active_object
        eligible, skipped = _collect_eligible(context, self.selected_only)
        selected = {obj.name for obj in context.view_layer.objects if obj.select_get()}

        problem = _join_problem(active, eligible, skipped)
        if problem:
            self.report(*problem)
            return {'CANCELLED'}

        bpy.ops.object.mode_set(mode='OBJECT')
        mirror_note = ""
        # Apply Mirror: the copies are made from the mirrored shape; the
        # originals only get it at the end, once the join has succeeded.
        mirrored = {}
        mesh_of = lambda obj: mirrored.get(obj.name, obj.data)
        placeholder = (bpy.data.materials.get(PLACEHOLDER_MATERIAL)
                       or bpy.data.materials.new(PLACEHOLDER_MATERIAL))
        started = time.perf_counter()
        face_sets = context.scene.sculpt_join_face_sets
        faces_expected = sum(1 for obj in eligible if len(obj.data.polygons) > 0)
        # Face Sets = None: join the meshes as they are. A mesh whose Face Sets
        # are only the default id counts as having none.
        face_set_action = [None] * len(eligible)
        if face_sets == 'NONE':
            real = [_has_real_face_sets(obj.data) for obj in eligible]
            if any(real):
                face_set_action = ['TAG' if not r else None for r in real]
            else:
                face_set_action = ['DROP'] * len(eligible)
        tag_no_face_sets = 'TAG' in face_set_action

        settings = context.scene
        proxied, proxy_notes = [], []
        copies, copy_meshes, entries, copy_active = [], [], [], None
        rests = []
        join_id = uuid.uuid4().hex[:12]
        try:
            if self.apply_mirror:
                for obj in eligible:
                    if _mirror_modifiers(obj):
                        yield 0.0, f"Mirroring {obj.name}"
                        mirrored[obj.name] = _mirrored_mesh(context, obj)
            plan = (_plan_proxies(eligible, settings.sculpt_join_budget, mesh_of)
                    if settings.sculpt_join_proxies else {})
            cost = [_face_count(mesh_of(o)) * (8 if o.name in plan else 1)
                    for o in eligible]
            total_cost, done_cost = float(sum(cost)) or 1.0, 0
            offset = 0
            for index, obj in enumerate(eligible):
                face_set = index + 1 if face_sets == 'MESH' else None
                rest = None
                proxy_mesh = None
                yield (0.9 * done_cost / total_cost,
                       f"Proxy for {obj.name}" if obj.name in plan else f"Copying {obj.name}")
                done_cost += cost[index]
                if obj.name in plan:
                    t_proxy = time.perf_counter()
                    proxy_mesh, method = _build_proxy_mesh(context, mesh_of(obj),
                                                           plan[obj.name])
                    if proxy_mesh is None:
                        proxy_notes.append(f"{obj.name}: no proxy, joined at full resolution")
                    else:
                        print(f"[Sculpt Join] proxy {obj.name}: {_face_count(mesh_of(obj)):,} -> "
                              f"{_face_count(proxy_mesh):,} faces ({method}, "
                              f"{time.perf_counter() - t_proxy:.2f} s)")
                if _has_multires(obj):
                    copy = _make_proxy(context, obj, index, placeholder,
                                       face_set, face_set_action[index],
                                       flip=_flips(obj, active))
                elif proxy_mesh is not None:
                    copy, rest = _make_dense_proxy(context, obj, index, proxy_mesh,
                                                   placeholder, face_set,
                                                   face_set_action[index],
                                                   flip=_flips(obj, active))
                    rests.append(rest)
                    proxied.append(obj)
                else:
                    copy = _make_copy(context, obj, index, placeholder, face_set,
                                      face_set_action[index], mirrored.get(obj.name),
                                      flip=_flips(obj, active))
                entry = {"id": index, "name": obj.name, "uid": f"{join_id}-{index}"}
                # every vertex gets an id, to find it again later
                entry["n"] = len(copy.data.vertices)
                entry["off"] = offset
                _tag_vertex_ids(copy.data, offset)
                offset += entry["n"]
                if rest is not None:
                    entry["rest"] = rest.name
                    entry["dense_n"] = len(mesh_of(obj).vertices)
                copies.append(copy)
                copy_meshes.append(copy.data)
                entries.append(entry)
                if obj == active:
                    copy_active = copy
            t_copies = time.perf_counter()
            yield 0.9, "Joining"

            _deselect_all(context)
            for copy in copies:
                copy.select_set(True)
            context.view_layer.objects.active = copy_active
            bpy.ops.object.join()
            t_joined = time.perf_counter()
        except BaseException as exc:  # rollback (also Esc): the originals were never touched
            _drop_copies(copies, copy_meshes + list(mirrored.values()))
            _drop_rest_meshes({"entries": [{"rest": r.name} for r in rests]})
            _remove_placeholder()
            _drop_temp_collection()
            context.view_layer.objects.active = active
            active.select_set(True)
            bpy.ops.object.mode_set(mode='SCULPT')
            if not isinstance(exc, Exception):
                raise                   # Esc / closed: the runner reports it
            self.report({'ERROR'}, f"Join failed: {exc}")
            return {'CANCELLED'}

        joined = context.view_layer.objects.active
        _drop_copies([], copy_meshes)   # meshes of the copies consumed by the join
        _remove_placeholder()           # no-op if some object is using it

        joined.name = JOINED_NAME
        joined.data.name = JOINED_NAME

        # The Apply depends on the vertex ids surviving the join. Check now,
        # while nothing is hidden yet, so a failure can be undone cleanly.
        if not _vertex_ids_ok(joined, offset):
            mesh = joined.data
            bpy.data.objects.remove(joined, do_unlink=True)
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
            _drop_rest_meshes({"entries": entries})
            _remove_placeholder()
            _drop_copies([], list(mirrored.values()))
            _drop_temp_collection()
            context.view_layer.objects.active = active
            active.select_set(True)
            bpy.ops.object.mode_set(mode='SCULPT')
            self.report({'ERROR'}, "Join failed: the join did not keep the vertex "
                                   "ids, so it could not be applied later.")
            return {'CANCELLED'}

        # The join is good: only now does Apply Mirror change the originals.
        if mirrored:
            changed, mirror_problems = 0, []
            for obj in eligible:
                mesh = mirrored.get(obj.name)
                if mesh is None:
                    continue
                try:
                    _commit_mirror(obj, mesh)
                    changed += 1
                except (RuntimeError, ValueError, TypeError) as exc:
                    mirror_problems.append(f"{obj.name}: Mirror not applied ({exc}), "
                                           f"its sculpt will not apply")
            _drop_copies([], list(mirrored.values()))
            if changed:
                mirror_note = f" Mirror applied on {_meshes(changed)}."
            if mirror_problems:
                mirror_note += " " + "; ".join(mirror_problems) + "."

        if tag_no_face_sets:
            _normalize_face_sets(joined.data)

        # Per Mesh Face Sets: confirm the join really carried them; otherwise
        # fall back to loose parts and say so.
        face_note = ""
        if face_sets == 'MESH' and not _face_sets_per_mesh_ok(joined, faces_expected):
            face_sets = 'PARTS'
            face_note = " Per Mesh Face Sets were not available; loose parts were used."

        # Single viewport color: the joined object looks like it has one
        # material. The real materials stay untouched.
        info = {"entries": entries, "active": active.name,
                "mirror_applied": [o.name for o in eligible if o.name in mirrored],
                "active_index": eligible.index(active),
                # The selection before the join, given back when it ends.
                "selected": [i for i, o in enumerate(eligible) if o.name in selected],
                "selected_other": sorted(selected - {o.name for o in eligible}),
                "verts": len(joined.data.vertices), "faces": len(joined.data.polygons)}
        # Remember WHICH viewport is changed, to give exactly that one back.
        space = _space_at(view)
        if view is not None and space is not None:
            info["view"] = view
            if context.scene.sculpt_join_single_color:
                info["shading_color_type"] = space.shading.color_type
                space.shading.color_type = 'SINGLE'
            # Statistics: show the numbers of the joined mesh while joined.
            info["stats_was_on"] = space.overlay.show_stats
            space.overlay.show_stats = True
        table = json.dumps(info)
        joined[DATA_KEY] = table
        context.scene[BACKUP_KEY] = table   # lets the originals come back if
                                            # the joined mesh gets deleted

        for obj, entry in zip(eligible, entries):   # tag and hide the originals
            obj[ORIGINAL_KEY] = entry["uid"]
            obj.hide_set(True)

        _deselect_all(context)
        joined.select_set(True)
        context.view_layer.objects.active = joined
        bpy.ops.object.mode_set(mode='SCULPT')

        if face_sets == 'PARTS':
            # Without the interface this sculpt operator crashes Blender
            # (seen in 4.2, 5.0 and 5.2), so it only runs with a window.
            if bpy.app.background or context.window is None:
                face_note = " Face Sets per loose part need the interface; none were created."
            else:
                try:
                    bpy.ops.sculpt.face_sets_init(mode='LOOSE_PARTS')
                except RuntimeError:
                    face_note = " Face Sets could not be created."

        elapsed = time.perf_counter() - started
        print(f"[Sculpt Join] join: copies "
              f"{t_copies - started:.2f} s, join {t_joined - t_copies:.2f} s, "
              f"total {elapsed:.2f} s")
        message = f"{_meshes(len(eligible))} joined ({_fmt_time(elapsed)})."
        if skipped:
            message += f" {_meshes(len(skipped))} left untouched."
        if proxied:
            message += (f" {_meshes(len(proxied))} posed through light proxies "
                        f"({len(joined.data.polygons):,} faces joined).")
        if proxy_notes:
            message += " " + "; ".join(proxy_notes) + "."
        message += mirror_note + face_note
        level = {'WARNING'} if (skipped or face_note or proxy_notes
                                or "not applied" in mirror_note) else {'INFO'}
        self.report(level, message)
        return {'FINISHED'}


class OBJECT_OT_sculpt_join_apply(_Steps, bpy.types.Operator):
    """Write the new vertex positions back to each original mesh. Everything else in the originals is kept"""
    bl_idname = "object.sculpt_join_apply"
    bl_label = "Apply to Originals"
    bl_options = {'REGISTER', 'UNDO'}
    _cancel_message = "Apply cancelled (Esc). The join is still there."

    @classmethod
    def poll(cls, context):
        return not _busy() and _joined_fast() is not None

    def execute(self, context):
        sculpt = context.mode == 'SCULPT'
        return self._start(context, self._apply(context, sculpt))

    def _apply(self, context, sculpt):
        """The apply, as steps (see _Steps): only the vertex positions go back."""
        started = time.perf_counter()
        joined = _joined_fast()
        info = _get_info(joined)
        try:
            _focus(context, joined)     # Object Mode: the sculpt is in the mesh
            restored, problems = yield from _write_positions(joined, info["entries"])
        except BaseException as exc:
            if sculpt:          # leave the join as it was, ready for another try
                try:
                    bpy.ops.object.mode_set(mode='SCULPT')
                except RuntimeError:
                    pass
            if not isinstance(exc, Exception):
                raise                   # Esc / closed: the runner reports it
            self.report({'ERROR'}, f"Apply failed: {exc}")
            return {'CANCELLED'}

        _discard_joined(context, joined, info, sculpt)
        elapsed = time.perf_counter() - started
        print(f"[Sculpt Join] apply: total {elapsed:.2f} s")
        if problems:
            self.report({'WARNING'},
                        f"{_meshes(restored)} updated ({_fmt_time(elapsed)}). Issues: "
                        + "; ".join(problems))
        else:
            self.report({'INFO'}, f"{_meshes(restored)} updated ({_fmt_time(elapsed)}).")
        return {'FINISHED'}


class OBJECT_OT_sculpt_join_cancel(bpy.types.Operator):
    """Discard the joined mesh and show the original meshes again, without applying the sculpt"""
    bl_idname = "object.sculpt_join_cancel"
    bl_label = "Cancel Join"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return not _busy() and _joined_fast() is not None

    def execute(self, context):
        sculpt = context.mode == 'SCULPT'
        joined = _joined_fast()
        info = _get_info(joined)
        _leave_mode(context)
        _discard_joined(context, joined, info, sculpt, restore_selection=True)
        applied = info["mirror_applied"]
        if applied:
            self.report({'WARNING'}, f"Join cancelled. Original meshes restored; the Mirror "
                        f"stays applied on {_meshes(len(applied))} (Ctrl+Z to undo it).")
        else:
            self.report({'INFO'}, "Join cancelled. Original meshes restored.")
        return {'FINISHED'}


class OBJECT_OT_sculpt_join_focus(bpy.types.Operator):
    """Go back to the joined mesh, in Sculpt Mode (e.g. after Transfer Sculpt Mode to another mesh, or after leaving Sculpt Mode)"""
    bl_idname = "object.sculpt_join_focus"
    bl_label = "Back to Join"
    bl_options = {'UNDO'}

    @classmethod
    def poll(cls, context):
        joined = _joined_fast()
        return (not _busy() and joined is not None
                and (context.mode != 'SCULPT' or context.active_object != joined))

    def execute(self, context):
        joined = _joined_fast()
        try:
            _focus(context, joined)
            bpy.ops.object.mode_set(mode='SCULPT')
        except RuntimeError as exc:
            self.report({'ERROR'}, f"Could not go back to the join: {exc}")
            return {'CANCELLED'}
        return {'FINISHED'}


class OBJECT_OT_sculpt_join_recover(bpy.types.Operator):
    """The joined mesh was deleted: show the hidden original meshes again and clean up. Whatever was sculpted on the joined mesh is lost (Ctrl+Z may bring the joined mesh back instead)"""
    bl_idname = "object.sculpt_join_recover"
    bl_label = "Restore Originals"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return not _busy() and _lost_info(context.scene) is not None

    def execute(self, context):
        info = _lost_info(context.scene)
        _leave_mode(context)
        # A joined mesh that is still in the file but in no scene goes too.
        for obj in [o for o in bpy.data.objects if DATA_KEY in o.keys()]:
            mesh = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        # Deleting the joined object leaves its mesh behind with no users. It
        # still holds the placeholder material, which would then be saved.
        for mesh in [m for m in bpy.data.meshes
                     if m.users == 0 and VERTEX_ID_ATTRIBUTE in m.attributes]:
            bpy.data.meshes.remove(mesh)
        _drop_rest_meshes(info)     # first: the rest shapes may use the placeholder
        _remove_placeholder()
        _drop_temp_collection()
        shown = _show_originals(info)
        _release_originals(info)
        _restore_view(context, info)
        _clear_backup()
        missing = len(info["entries"]) - len(shown)
        message = f"{_meshes(len(shown))} shown again."
        if missing:
            message += f" {_meshes(missing)} not found."
        self.report({'WARNING'} if missing else {'INFO'}, message)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Topology guard: the Apply needs the same vertices, so warn at once when a
# remesh (or anything else) changes them, and keep Dyntopo off while joined.
# ---------------------------------------------------------------------------

_GUARD = {"bad": False, "dyntopo_note": ""}


def _joined_fast():
    """The joined object of the current scene. Cheap when there is no join
    (runs on every update and every redraw): the scene says so first."""
    scene = bpy.context.scene
    if scene is None or scene.get(BACKUP_KEY) is None:
        return None
    obj = bpy.data.objects.get(JOINED_NAME)
    if obj is not None and DATA_KEY in obj.keys() and obj.users_scene:
        return obj
    return _find_joined()


def _topology_changed(joined, info):
    return (len(joined.data.vertices) != info["verts"]
            or len(joined.data.polygons) != info["faces"])


def _turn_off_dyntopo():
    """Timer: switch Dyntopo off on the joined mesh (needs a 3D View context)."""
    joined = _joined_fast()
    if joined is None or not getattr(joined, "use_dynamic_topology_sculpting", False):
        return None
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            try:
                with bpy.context.temp_override(window=window, area=area, region=region,
                                               object=joined, active_object=joined):
                    bpy.ops.sculpt.dynamic_topology_toggle()
                _GUARD["dyntopo_note"] = "Dyntopo was turned off: it changes the topology"
                _redraw_views()
                return None
            except (RuntimeError, TypeError):
                continue
    try:                                # no window (scripts): try without one
        with bpy.context.temp_override(object=joined, active_object=joined):
            bpy.ops.sculpt.dynamic_topology_toggle()
        _GUARD["dyntopo_note"] = "Dyntopo was turned off: it changes the topology"
    except (RuntimeError, TypeError):
        pass
    return None


@bpy.app.handlers.persistent
def _guard_update(*_args):
    joined = _joined_fast()
    if joined is None:
        bad, dyntopo = False, False
    else:
        info = _get_info(joined) or {}
        bad = _topology_changed(joined, info)
        dyntopo = getattr(joined, "use_dynamic_topology_sculpting", False)
    if dyntopo and not bpy.app.timers.is_registered(_turn_off_dyntopo):
        bpy.app.timers.register(_turn_off_dyntopo, first_interval=0.05)
    if bad != _GUARD["bad"]:
        _GUARD["bad"] = bad
        _redraw_views()
    if joined is None and _GUARD["dyntopo_note"]:
        _GUARD["dyntopo_note"] = ""


_GUARD_HANDLERS = ("depsgraph_update_post", "undo_post", "redo_post", "load_post")


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class OBJECT_PT_sculpt_join(bpy.types.Panel):
    """Sculpt Join panel in the 3D Viewport sidebar (Sculpt Mode)"""
    bl_label = f"Sculpt Join {VERSION}".strip()
    bl_idname = "OBJECT_PT_sculpt_join"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Sculpt Join'

    @classmethod
    def poll(cls, context):
        obj = context.object
        if _busy():         # keep the panel while working (Object/Edit Mode inside)
            return True
        if context.scene.get(BACKUP_KEY) is not None:   # a join, in any mode
            return True
        return (context.mode == 'SCULPT' and obj is not None
                and obj.type == 'MESH')

    def draw(self, context):
        layout = self.layout
        if _busy():
            layout.label(text=f"Working: {_PROGRESS.get('text', '')}")
            layout.label(text="Press Esc to cancel")
            return
        joined = _joined_fast()
        if joined is not None:
            info = _get_info(joined)
            layout.label(text=f"Join in progress ({_meshes(len(info['entries']))})")
            if _topology_changed(joined, info):
                box = layout.box()
                box.alert = True
                box.label(text="Topology changed: this join", icon='ERROR')
                box.label(text="can't be applied. Ctrl+Z to undo.")
            if _GUARD["dyntopo_note"]:
                layout.label(text=_GUARD["dyntopo_note"], icon='INFO')
            if context.mode != 'SCULPT':
                layout.label(text="Outside Sculpt Mode", icon='INFO')
            if context.mode != 'SCULPT' or context.active_object != joined:
                layout.operator(OBJECT_OT_sculpt_join_focus.bl_idname)
            layout.operator(OBJECT_OT_sculpt_join_apply.bl_idname)
            layout.operator(OBJECT_OT_sculpt_join_cancel.bl_idname)
            return

        lost = _lost_info(context.scene)
        if lost is not None:
            box = layout.box()
            box.alert = True
            box.label(text="The joined mesh is gone", icon='ERROR')
            box.label(text=f"{_meshes(len(lost['entries']))} still hidden.")
            box.label(text="Ctrl+Z may bring it back, or:")
            layout.operator(OBJECT_OT_sculpt_join_recover.bl_idname, icon='HIDE_OFF')
            return

        if (context.mode != 'SCULPT' or context.object is None
                or context.object.type != 'MESH'):
            return

        settings = context.scene    # saved with the .blend file
        col = layout.column(align=True)
        col.label(text="Pose and sculpt the parts as one.")
        col.label(text="Don't use Dyntopo or Remesh while joined.")

        selected_only = settings.sculpt_join_selected_only
        visible, skipped = _collect_eligible(context)
        targets, target_skipped = (_collect_eligible(context, selected_only=True)
                                   if selected_only else (visible, skipped))

        # 2) Options, folded away
        header, body = layout.panel("OBJECT_PT_sculpt_join_options", default_closed=True)
        header.label(text="Options")
        if body is not None:
            body.prop(settings, "sculpt_join_proxies")
            sub = body.row()
            sub.active = settings.sculpt_join_proxies
            sub.prop(settings, "sculpt_join_budget", text="Face Limit")
            if settings.sculpt_join_proxies:
                body.label(text="For fine detail, turn Dense Proxies off")
            body.prop(settings, "sculpt_join_face_sets")
            body.prop(settings, "sculpt_join_single_color")
            body.prop(settings, "sculpt_join_warn_deform")

        # 3) Join
        reason = _skip_reason(context.object)
        if reason:      # blocks the join: say it here
            layout.label(text=f"Active mesh: {reason}", icon='ERROR')
        notes = (len(target_skipped)
                 + sum(1 for o in targets if _mirror_modifiers(o))
                 + len(_deform_note_objects(context, targets)))
        if notes and not reason:
            layout.label(text=f"{notes} note{'s' if notes > 1 else ''} to review on Join",
                         icon='INFO')
        layout.prop(settings, "sculpt_join_selected_only")
        row = layout.row()
        row.scale_y = 1.4
        row.enabled = len(targets) >= 2
        op = row.operator(OBJECT_OT_sculpt_join_start.bl_idname,
                          text=f"Join ({_meshes(len(targets))})")
        op.selected_only = selected_only
        if selected_only and len(targets) < 2:
            layout.label(text="Select 2+ parts (Outliner or Object Mode)")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

CLASSES = (
    OBJECT_OT_sculpt_join_start,
    OBJECT_OT_sculpt_join_apply,
    OBJECT_OT_sculpt_join_cancel,
    OBJECT_OT_sculpt_join_focus,
    OBJECT_OT_sculpt_join_recover,
    OBJECT_PT_sculpt_join,
)


def register():
    bpy.types.Scene.sculpt_join_proxies = bpy.props.BoolProperty(
        name="Dense Proxies",
        description=("When the scene has more faces than the Face Limit, "
                     "dense meshes without Multires join as light proxies, sized "
                     "by surface area. On Apply the pose is carried to every "
                     "vertex of the dense originals, details included. Good for "
                     "posing and big shape changes; fine detail sculpted on a "
                     "proxy is not carried exactly: turn this off for fine detail"),
        default=True,
    )
    bpy.types.Scene.sculpt_join_budget = bpy.props.IntProperty(
        name="Face Limit",
        description=("About how many faces the joined mesh should have "
                     "(a target, it can end a little above). Shared by surface "
                     "area; only meshes denser than their share get a proxy. "
                     "Higher: proxies closer to the originals, heavier brushes. "
                     "Lower: lighter and faster, coarser bends"),
        default=500_000, min=20_000, soft_max=3_000_000, step=50_000,
    )
    bpy.types.Scene.sculpt_join_selected_only = bpy.props.BoolProperty(
        name="Selected Only",
        description=("Join only the selected meshes (plus the active one). Select "
                     "the parts in the Outliner, or in Object Mode before entering "
                     "Sculpt Mode. Off: all visible meshes are joined"),
        default=False,
    )
    bpy.types.Scene.sculpt_join_single_color = bpy.props.BoolProperty(
        name="Single Viewport Color",
        description=("In Solid shading, set the viewport color to Single while "
                     "joined, so the joined mesh looks like it has one material. "
                     "The real materials are not changed; the previous color "
                     "is restored afterwards"),
        default=True,
    )
    bpy.types.Scene.sculpt_join_warn_deform = bpy.props.BoolProperty(
        name="Warn About Deform Modifiers",
        description=("Before joining, list the meshes with deforming modifiers "
                     "(Armature, Lattice, Shrinkwrap...). While joined they show "
                     "their base shape (Armature: rest pose); the modifiers stay "
                     "on the originals and work again after Apply"),
        default=True,
    )
    bpy.types.Scene.sculpt_join_face_sets = bpy.props.EnumProperty(
        name="Face Sets",
        description=("Create Face Sets when joining, so parts can be masked, "
                     "hidden or posed as segments. Overwrites existing Face Sets"),
        items=[
            ('NONE', "None", "Do not create Face Sets"),
            ('MESH', "Per Mesh", "One Face Set for each joined mesh"),
            ('PARTS', "Per Loose Part",
             "One Face Set for each loose part of the joined mesh (a mesh made "
             "of separate pieces gets one per piece)"),
        ],
        default='MESH',   # one Face Set per mesh: easy to isolate parts
    )
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    _OVERLAY["handle"] = bpy.types.SpaceView3D.draw_handler_add(
        _draw_overlay, (), 'WINDOW', 'POST_PIXEL')
    for name in _GUARD_HANDLERS:
        getattr(bpy.app.handlers, name).append(_guard_update)


def unregister():
    if _OVERLAY["handle"] is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_OVERLAY["handle"], 'WINDOW')
        _OVERLAY["handle"] = None
    _PROGRESS.clear()
    for name in _GUARD_HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if _guard_update in handlers:
            handlers.remove(_guard_update)
    if bpy.app.timers.is_registered(_turn_off_dyntopo):
        bpy.app.timers.unregister(_turn_off_dyntopo)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.sculpt_join_warn_deform
    del bpy.types.Scene.sculpt_join_face_sets
    del bpy.types.Scene.sculpt_join_selected_only
    del bpy.types.Scene.sculpt_join_budget
    del bpy.types.Scene.sculpt_join_proxies
    del bpy.types.Scene.sculpt_join_single_color

