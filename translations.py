from bpy.app import translations


# Keep common labels such as "None" scoped to this add-on.
CONTEXT = "Sculpt Join"


def iface_(message):
    return translations.pgettext_iface(message, CONTEXT)


def report_(message):
    return translations.pgettext_rpt(message, CONTEXT)


_SIMPLIFIED_CHINESE = {
    # Panel and options
    "Pose and sculpt the parts as one.": "将多个部件作为整体摆姿和雕刻。",
    "Don't use Dyntopo or Remesh while joined.": "合并期间请勿使用动态拓扑或重构网格。",
    "Dense Proxies": "高面数网格代理",
    ("When the scene has more faces than the Face Limit, "
     "dense meshes without Multires join as light proxies, sized "
     "by surface area. On Apply the pose is carried to every "
     "vertex of the dense originals, details included. Good for "
     "posing and big shape changes; fine detail sculpted on a "
     "proxy is not carried exactly: turn this off for fine detail"):
        "当场景面数超过面数上限时，没有多级精度修改器的高面数网格会使用简化代理，"
        "代理面数按表面积分配。应用时，形变传递给原网格的每个顶点，并保留原有细节。"
        "适合摆姿和大幅调整形状。代理上新雕刻的细节可能有损失，精细雕刻时请关闭此选项",
    "Face Limit": "面数上限",
    ("About how many faces the joined mesh should have "
     "(a target, it can end a little above). Shared by surface "
     "area; only meshes denser than their share get a proxy. "
     "Higher: proxies closer to the originals, heavier brushes. "
     "Lower: lighter and faster, coarser bends"):
        "合并网格的目标面数，实际面数可能略高。按表面积分配额度，只有面数超出各自额度的网格才会使用代理。"
        "数值越高，代理越接近原网格，笔刷开销越大。数值越低，操作越快，形变越粗略",
    "For fine detail, turn Dense Proxies off": "精细雕刻时请关闭高面数网格代理",
    "Selected Only": "仅选中",
    "Join only the selected meshes (plus the active one)": "仅合并选中的网格和活动网格",
    ("Join only the selected meshes (plus the active one). Select "
     "the parts in the Outliner, or in Object Mode before entering "
     "Sculpt Mode. Off: all visible meshes are joined"):
        "仅合并选中的网格和活动网格。可在大纲视图中选择部件，或在进入雕刻模式前于物体模式中选择。"
        "关闭时合并所有可见网格",
    "Single Viewport Color": "统一视图颜色",
    ("In Solid shading, set the viewport color to Single while "
     "joined, so the joined mesh looks like it has one material. "
     "The real materials are not changed; the previous color "
     "is restored afterwards"):
        "合并期间将实体着色的视图颜色设为单色。实际材质不受影响，结束后恢复原来的视图颜色设置",
    "Warn About Deform Modifiers": "提醒变形修改器",
    ("Before joining, list the meshes with deforming modifiers "
     "(Armature, Lattice, Shrinkwrap...). While joined they show "
     "their base shape (Armature: rest pose); the modifiers stay "
     "on the originals and work again after Apply"):
        "合并前列出带骨架、晶格、缩裹等变形修改器的网格。合并期间显示这些网格的基础形状"
        "（骨架使用静置姿势）。修改器保留在原物体上，应用后继续生效",
    "Face Sets": "面组",
    ("Create Face Sets when joining, so parts can be masked, "
     "hidden or posed as segments. Overwrites existing Face Sets"):
        "合并时创建面组，以便按部件遮罩、隐藏或摆姿。这会覆盖临时网格上的已有面组",
    "None": "无",
    "Do not create Face Sets": "不创建面组",
    "Per Mesh": "按网格",
    "One Face Set for each joined mesh": "每个参与合并的网格各建一个面组",
    "Per Loose Part": "按松散部件",
    ("One Face Set for each loose part of the joined mesh (a mesh made "
     "of separate pieces gets one per piece)"):
        "为合并网格中每个独立的部件各建一个面组",
    "Working: {step}": "处理中：{step}",
    "Press Esc to cancel": "按 Esc 取消",
    "Join in progress ({meshes})": "正在合并雕刻（{meshes}）",
    "Topology changed: this join": "拓扑已改变，无法应用。",
    "can't be applied. Ctrl+Z to undo.": "按 Ctrl+Z 撤销。",
    "Dyntopo was turned off: it changes the topology": "动态拓扑会改变网格拓扑，已将其关闭",
    "Outside Sculpt Mode": "当前已退出雕刻模式",
    "The joined mesh is gone": "合并网格已丢失",
    "{meshes} still hidden.": "仍有 {meshes} 处于隐藏状态。",
    "Ctrl+Z may bring it back, or:": "可尝试按 Ctrl+Z 找回，或执行以下操作：",
    "Active mesh: {reason}": "活动网格：{reason}",
    "{count} note to review on Join": "合并前有 {count} 条提示需要查看",
    "{count} notes to review on Join": "合并前有 {count} 条提示需要查看",
    "Join ({meshes})": "合并（{meshes}）",
    "Select 2+ parts (Outliner or Object Mode)": "请在大纲视图或物体模式中选择至少两个部件",
    "{count} mesh": "{count} 个网格",
    "{count} meshes": "{count} 个网格",

    # Operators and confirmation dialog
    "Join Visible": "合并可见网格",
    ("Join copies of all visible meshes into one mesh, to sculpt or pose them together. "
     "In Solid shading, the viewport color can be set to Single while joined"):
        "将所有可见网格的副本合并，便于一起雕刻或摆姿。合并期间可将实体着色的视图颜色设为单色",
    ("Join copies of all visible meshes into one mesh, to sculpt "
     "or pose them together. In Solid shading, the viewport color "
     "can be set to Single while joined. Avoid Dyntopo and remesh "
     "tools while joined"):
        "将所有可见网格的副本合并，便于一起雕刻或摆姿。合并期间可将实体着色的视图颜色设为单色。"
        "请勿使用动态拓扑或重构网格工具",
    ("Join only the selected meshes (plus the active one). "
     "Select the parts in the Outliner, or in Object Mode "
     "before entering Sculpt Mode. Avoid Dyntopo and remesh "
     "tools while joined"):
        "仅合并选中的网格和活动网格。可在大纲视图中选择部件，或在进入雕刻模式前于物体模式中选择。"
        "合并期间请勿使用动态拓扑或重构网格工具",
    "Apply to Originals": "应用到原物体",
    "Write the new vertex positions back to each original mesh. Everything else in the originals is kept":
        "将新的顶点位置写回各个原网格，保留其余数据",
    "Cancel Join": "取消合并",
    "Discard the joined mesh and show the original meshes again, without applying the sculpt":
        "丢弃合并网格并重新显示原网格，不应用雕刻结果",
    "Back to Join": "返回合并雕刻",
    ("Go back to the joined mesh, in Sculpt Mode (e.g. after Transfer Sculpt Mode "
     "to another mesh, or after leaving Sculpt Mode)"):
        "回到合并网格的雕刻模式，例如雕刻模式已转移到另一个网格或已退出时",
    "Restore Originals": "恢复原物体",
    ("The joined mesh was deleted: show the hidden original meshes again and clean up. "
     "Whatever was sculpted on the joined mesh is lost (Ctrl+Z may bring the joined mesh back instead)"):
        "合并网格已被删除。重新显示隐藏的原网格并清理临时数据。合并网格上的雕刻结果会丢失"
        "（可尝试按 Ctrl+Z 找回合并网格）",
    "Before Joining": "合并前确认",
    "Join Remaining": "合并其余网格",
    "Join": "合并",
    "Apply Mirror modifiers permanently": "永久应用镜像修改器",
    ("Apply the Mirror modifiers of the originals, so both halves "
     "join. The originals only change once the join succeeded "
     "(Esc leaves them untouched); then the Mirror is gone "
     "(Ctrl+Z undoes it). Off: only the real half joins"):
        "应用原物体的镜像修改器，让两侧都参与合并。只有合并成功后才会修改原物体并移除镜像修改器。"
        "按 Esc 可取消，按 Ctrl+Z 可撤销。关闭时仅合并原有的一侧",
    "{meshes} with deforming modifiers:": "有 {meshes} 带有变形修改器：",
    "... and {count} more": "…另有 {count} 项",
    "While joined they show their base shape.": "合并期间显示这些网格的基础形状。",
    "While joined they show their base shape (Armature: rest pose).":
        "合并期间显示这些网格的基础形状（骨架使用静置姿势）。",
    "The modifiers stay and work again after Apply.": "修改器会保留，并在应用后继续生效。",
    "Keep warning about deforming modifiers": "继续提醒变形修改器",
    "These meshes stay untouched in the scene:": "场景中的这些网格不会参与合并：",
    "{meshes} with Mirror modifiers:": "有 {meshes} 带有镜像修改器：",
    "{name} (Mirror not first: the result can differ)": "{name}（镜像修改器不在首位，结果可能不同）",
    "Off: only the real half of each mesh is joined.": "关闭时，每个网格只合并原有的一侧。",
    "linked data": "链接数据",
    "no vertices": "没有顶点",
    "no faces (edges or points only)": "没有面（只有边或点）",
    "has Shape Keys": "带有形态键",
    "shares its mesh data with another object": "与其他物体共享网格数据",
    "not eligible": "不符合合并条件",

    # Progress and reports
    "Sculpt Join: topology changed, this join can't be applied": "Sculpt Join：拓扑已改变，无法应用",
    "Press Ctrl+Z to undo the remesh (or Cancel Join)": "按 Ctrl+Z 撤销重构网格，或取消合并",
    "Esc to cancel": "按 Esc 取消",
    "Starting": "正在准备",
    "Mirroring {name}": "正在镜像 {name}",
    "Proxy for {name}": "正在为 {name} 创建代理",
    "Copying {name}": "正在复制 {name}",
    "Joining": "正在合并",
    "Applying {name}": "正在应用到 {name}",
    "Carrying pose to {name}": "正在将形变传递到 {name}",
    "Writing": "正在写回",
    "{seconds:.1f} s": "{seconds:.1f} 秒",
    "{minutes} min {seconds:02d} s": "{minutes} 分 {seconds:02d} 秒",
    "The active mesh cannot be joined: {reason}.": "无法合并活动网格：{reason}。",
    "At least 2 meshes are needed. Check visibility and the selection.":
        "至少需要两个网格，请检查可见性和选择状态。",
    "Sculpt Join stopped: {error}": "Sculpt Join 已停止：{error}",
    "Join cancelled (Esc). Nothing was changed.": "已按 Esc 取消合并，原物体未被修改。",
    "Join failed: {error}": "合并失败：{error}",
    "Join failed: the join did not keep the vertex ids, so it could not be applied later.":
        "合并失败：顶点 ID 未保留，无法在之后应用到原网格。",
    "Mirror applied on {meshes}.": "已在 {meshes} 上应用镜像修改器。",
    "{name}: Mirror not applied ({error}), its sculpt will not apply":
        "{name}：镜像修改器应用失败（{error}），该网格的雕刻结果将无法写回",
    "Per Mesh Face Sets were not available; loose parts were used.":
        "无法按网格创建面组，已改用松散部件。",
    "Face Sets per loose part need the interface; none were created.":
        "按松散部件创建面组需要图形界面，本次未创建面组。",
    "Face Sets could not be created.": "无法创建面组。",
    "{meshes} joined ({time}).": "已合并 {meshes}（耗时 {time}）。",
    "{meshes} left untouched.": "{meshes} 未参与合并。",
    "{meshes} posed through light proxies ({faces:,} faces joined).":
        "{meshes} 使用了简化代理（合并后共 {faces:,} 个面）。",
    "{name}: no proxy, joined at full resolution": "{name}：未生成代理，已按原面数合并",
    "Apply cancelled (Esc). The join is still there.": "已按 Esc 取消应用，合并网格仍然保留。",
    "Apply failed: {error}": "应用失败：{error}",
    ("the joined mesh changed (Dyntopo, remesh or deleted geometry). The join needs the same "
     "vertices: undo with Ctrl+Z, or Cancel Join"):
        "合并网格已改变（动态拓扑、重构网格或删除几何体）。应用需要原有顶点，请按 Ctrl+Z 撤销或取消合并",
    "{name}: original missing (left as is)": "{name}：原物体已丢失（已跳过）",
    "{name}: original changed (left as is)": "{name}：原物体已改变（已跳过）",
    "{name}: vertices missing (left as is)": "{name}：缺少顶点（已跳过）",
    "{name}: proxy rest shape missing (left as is)": "{name}：缺少代理的初始形状（已跳过）",
    "{meshes} updated ({time}).": "已更新 {meshes}（耗时 {time}）。",
    "Issues: {details}": "发现问题：{details}",
    "Join cancelled. Original meshes restored.": "已取消合并，并恢复原网格。",
    ("Join cancelled. Original meshes restored; the Mirror "
     "stays applied on {meshes} (Ctrl+Z to undo it)."):
        "已取消合并并恢复原网格。{meshes} 上的镜像修改器仍处于已应用状态，可按 Ctrl+Z 撤销。",
    "Could not go back to the join: {error}": "无法返回合并雕刻：{error}",
    "{meshes} shown again.": "已重新显示 {meshes}。",
    "{meshes} not found.": "未找到 {meshes}。",
}


_CATALOG = {(CONTEXT, source): target for source, target in _SIMPLIFIED_CHINESE.items()}
# Blender uses zh_CN in older releases and zh_HANS in newer ones.
TRANSLATIONS = {"zh_CN": _CATALOG, "zh_HANS": _CATALOG}
