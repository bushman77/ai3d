# Mara Venn

- `prompt.txt`: the full design brief (Qwen text-to-image prompt).
- Approved front image: `approved_references/mara_body_front_approved.png`.

```bash
cd ~/ai3d
python3 -m ai3d generate --name mara_v1 \
  --image approved_references/mara_body_front_approved.png --stop-after views
# check outputs/mara_v1/01_view_*.png, then:
python3 -m ai3d generate --name mara_v1 \
  --image approved_references/mara_body_front_approved.png --resume
```

The approved image shows Mara in the jumpsuit without belt or tools. Add
equipment later as separate props attached to bones (for example the
`mixamorig:Hips` bone for a belt), not as part of the body mesh.
