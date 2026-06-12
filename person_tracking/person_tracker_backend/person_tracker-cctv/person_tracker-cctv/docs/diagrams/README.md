Diagrams rendering instructions

These diagrams are PlantUML sources. To render them locally:

1) Install PlantUML and Graphviz, or use the PlantUML Docker image.

Example using Docker (recommended):

```bash
# render a single diagram to PNG
docker run --rm -v "$PWD":/workspace plantuml/plantuml -tpng docs/diagrams/system_architecture.puml

# render all puml files in directory
for f in docs/diagrams/*.puml; do \
  docker run --rm -v "$PWD":/workspace plantuml/plantuml -tpng "$f"; \
  echo "Rendered $f"; \
 done
```

2) Or install plantuml (Java) + graphviz and run:

```bash
plantuml -tpng docs/diagrams/system_architecture.puml
```

If you want, I can render these into PNG/SVG and add them to the repo. Request that and I will generate images and update the docs.
