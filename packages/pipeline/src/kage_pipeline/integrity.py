"""
Python port of @kage/ir `validateIRIntegrity`.

TS 側 (packages/ir/src/schema.ts:validateIRIntegrity) と同じ制約を検査する。
このチェックを pipeline 出力前に通すことで、editor/generator に渡ったあと TS 側で
再 parse しても高確率で整合する。
"""

from __future__ import annotations

from .ir_schema import Component, IR


def validate_ir_integrity(ir: IR) -> list[str]:
    errors: list[str] = []

    screen_ids = {str(s.id) for s in ir.screens}
    action_ids = {str(a.id) for a in ir.apiActions}
    entity_ids = {str(e.id) for e in ir.entities}
    data_binding_ids = {str(d.id) for d in ir.dataBindings}
    shared_state_ids = {str(s.id) for s in ir.sharedStates}

    for t in ir.transitions:
        if str(t.from_) not in screen_ids:
            errors.append(f"transition {t.id}: from {t.from_} not found")
        if str(t.to) not in screen_ids:
            errors.append(f"transition {t.id}: to {t.to} not found")
        for aid in t.actionIds:
            if aid not in action_ids:
                errors.append(f"transition {t.id}: action {aid} not found")
        for sid in t.updatesSharedStateIds:
            if sid not in shared_state_ids:
                errors.append(f"transition {t.id}: sharedState {sid} not found")

    for db in ir.dataBindings:
        if str(db.apiActionId) not in action_ids:
            errors.append(f"dataBinding {db.id}: apiAction {db.apiActionId} not found")

    for s in ir.screens:
        for db_id in s.initialDataBindingIds:
            if db_id not in data_binding_ids:
                errors.append(f"screen {s.id}: initialDataBinding {db_id} not found")

    for action in ir.apiActions:
        for eid in action.entityIds:
            if eid not in entity_ids:
                errors.append(f"apiAction {action.id}: entity {eid} not found")

    def walk_component(c: Component, screen_id: str) -> None:
        for db_id in c.dataBindingIds:
            if db_id not in data_binding_ids:
                errors.append(
                    f"component {c.id} in screen {screen_id}: dataBinding {db_id} not found"
                )
        for aid in c.actionIds:
            if aid not in action_ids:
                errors.append(f"component {c.id} in screen {screen_id}: action {aid} not found")
        for child in c.children:
            walk_component(child, screen_id)

    for s in ir.screens:
        walk_component(s.root, str(s.id))

    return errors
