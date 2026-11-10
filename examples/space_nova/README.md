# Space Nova integration examples

This folder is an **example consumer** of the project-independent AI3D
toolkit, not a required AI3D dependency.

`characters/mara_venn.json` illustrates a durable character card for
a full-body spaceport engineer with separate head, hair, outfit, hands and
equipment definitions. Its head prompt is independent of the full-body
reference to support controlled shape reconstruction experiments.

```bash
python3 -m ai3d character validate examples/space_nova/characters/mara_venn.json
```

The example specifies design intent only: it does **not** fetch images,
regenerate meshes, or join a head to a body automatically.
