Diagrama ER Interativo
======================

.. raw:: html

    <style>
        .interactive-diagram-container {
            width: 100%;
            height: 85vh;
            min-height: 600px;
            background: white;
            border: 2px solid #667eea;
            border-radius: 8px;
            overflow: hidden;
            margin: 20px 0;
        }
    </style>

    <div class="interactive-diagram-container">

.. raw:: html

    <div style="display: flex; flex-direction: column; height: 100%; width: 100%;">
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 15px 20px;">
            <h1 style="margin: 0; font-size: 24px;">🗂️ Diagrama ER Interativo - Sistema TIA</h1>
            <p style="margin: 5px 0 0 0; opacity: 0.9; font-size: 14px;">Arraste os nós | Zoom com scroll | Duplo clique para fixar</p>
        </div>
        
        <div style="padding: 10px 15px; background: #f8f9fa; border-bottom: 1px solid #dee2e6; display: flex; flex-wrap: wrap; gap: 8px;">
            <button onclick="resetZoom()" style="padding: 8px 12px; border: none; border-radius: 4px; background: #667eea; color: white; cursor: pointer; font-size: 14px;">🔄 Reset Zoom</button>
            <button onclick="fitToScreen()" style="padding: 8px 12px; border: none; border-radius: 4px; background: #667eea; color: white; cursor: pointer; font-size: 14px;">📐 Ajustar Tela</button>
            <button onclick="toggleLabels()" style="padding: 8px 12px; border: none; border-radius: 4px; background: #667eea; color: white; cursor: pointer; font-size: 14px;">🏷️ Toggle Labels</button>
            <button onclick="centerGraph()" style="padding: 8px 12px; border: none; border-radius: 4px; background: #667eea; color: white; cursor: pointer; font-size: 14px;">🎯 Centralizar</button>
        </div>
        
        <div id="diagram-container" style="flex: 1; position: relative; overflow: hidden; min-height: 0;">
            <svg id="diagram" style="width: 100%; height: 100%;"></svg>
        </div>
        
        <div style="padding: 10px 15px; background: #f8f9fa; border-top: 1px solid #dee2e6; display: flex; flex-wrap: wrap; gap: 15px; font-size: 14px;">
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="width: 20px; height: 20px; background: #e3f2fd; border: 3px solid #1976d2; border-radius: 3px;"></span>
                <span>Dimensão (D_*)</span>
            </div>
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="width: 20px; height: 20px; background: #fff3e0; border: 3px solid #f57c00; border-radius: 3px;"></span>
                <span>Fato (F_*)</span>
            </div>
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="width: 20px; height: 20px; background: #f3e5f5; border: 3px solid #7b1fa2; border-radius: 3px;"></span>
                <span>Outras</span>
            </div>
        </div>
    </div>

    <script src="https://d3js.org/d3.v7.min.js"></script>
    <script>
        (function() {
            const graphData = {
                nodes: [
        {
                "id": "D_CLASSROOM",
                "type": "dimension",
                "columns": 9
        },
        {
                "id": "D_HEALTH",
                "type": "dimension",
                "columns": 13
        },
        {
                "id": "D_SCHOOL",
                "type": "dimension",
                "columns": 13
        },
        {
                "id": "D_SCHOOL_GEOGRAPH",
                "type": "dimension",
                "columns": 6
        },
        {
                "id": "D_STUDENT",
                "type": "dimension",
                "columns": 22
        },
        {
                "id": "D_STUDENT_DISCIPLINE",
                "type": "dimension",
                "columns": 17
        },
        {
                "id": "F_CLASS",
                "type": "fact",
                "columns": 13
        },
        {
                "id": "F_STUDENT_CLASS",
                "type": "fact",
                "columns": 10
        },
        {
                "id": "F_AVALIATION",
                "type": "fact",
                "columns": 6
        },
        {
                "id": "F_ENROLLMENT",
                "type": "fact",
                "columns": 11
        },
        {
                "id": "classroom",
                "type": "other",
                "columns": 8
        }
],
                links: [
        {
                "source": "D_SCHOOL_GEOGRAPH",
                "target": "D_SCHOOL",
                "label": "F_HASH_ID"
        },
        {
                "source": "D_STUDENT_DISCIPLINE",
                "target": "D_STUDENT",
                "label": "F_HASH_ID"
        },
        {
                "source": "F_CLASS",
                "target": "D_CLASSROOM",
                "label": "classroom_id"
        },
        {
                "source": "F_CLASS",
                "target": "D_SCHOOL",
                "label": "school_id"
        },
        {
                "source": "F_STUDENT_CLASS",
                "target": "D_STUDENT",
                "label": "student_id"
        },
        {
                "source": "F_STUDENT_CLASS",
                "target": "F_CLASS",
                "label": "class_id"
        },
        {
                "source": "F_AVALIATION",
                "target": "D_STUDENT",
                "label": "student_id"
        },
        {
                "source": "F_AVALIATION",
                "target": "D_STUDENT_DISCIPLINE",
                "label": "discipline_id"
        },
        {
                "source": "F_ENROLLMENT",
                "target": "D_SCHOOL",
                "label": "school_id"
        },
        {
                "source": "F_ENROLLMENT",
                "target": "D_CLASSROOM",
                "label": "classroom_id"
        },
        {
                "source": "F_ENROLLMENT",
                "target": "D_STUDENT",
                "label": "student_id"
        },
        {
                "source": "F_ENROLLMENT",
                "target": "D_HEALTH",
                "label": "health_id"
        },
        {
                "source": "F_AVALIATION",
                "target": "D_STUDENT",
                "label": "student_id"
        },
        {
                "source": "F_AVALIATION",
                "target": "D_STUDENT_DISCIPLINE",
                "label": "discipline_id"
        },
        {
                "source": "F_ENROLLMENT",
                "target": "D_SCHOOL",
                "label": "school_id"
        },
        {
                "source": "F_ENROLLMENT",
                "target": "D_CLASSROOM",
                "label": "classroom_id"
        },
        {
                "source": "F_ENROLLMENT",
                "target": "D_STUDENT",
                "label": "student_id"
        },
        {
                "source": "F_ENROLLMENT",
                "target": "D_HEALTH",
                "label": "health_id"
        }
]
            };

            let width, height, svg, g, simulation, link, linkLabel, node;
            let labelsVisible = true;

            function initDiagram() {
                const container = document.getElementById('diagram-container');
                if (!container) return;
                
                width = container.clientWidth;
                height = container.clientHeight;

                svg = d3.select("#diagram")
                    .attr("width", width)
                    .attr("height", height);

                svg.selectAll("*").remove();
                g = svg.append("g");

                const zoom = d3.zoom()
                    .scaleExtent([0.1, 4])
                    .on("zoom", (event) => {
                        g.attr("transform", event.transform);
                    });

                svg.call(zoom);

                const nodes = graphData.nodes.map(d => ({...d}));
                const links = graphData.links.map(d => ({...d}));

                simulation = d3.forceSimulation(nodes)
                    .force("link", d3.forceLink(links).id(d => d.id).distance(150))
                    .force("charge", d3.forceManyBody().strength(-1000))
                    .force("center", d3.forceCenter(width / 2, height / 2))
                    .force("collision", d3.forceCollide().radius(60));

                link = g.append("g")
                    .selectAll("path")
                    .data(links)
                    .join("path")
                    .attr("stroke", "#999")
                    .attr("stroke-opacity", 0.6)
                    .attr("stroke-width", 2)
                    .attr("fill", "none")
                    .style("cursor", "pointer")
                    .on("mouseover", function() {
                        d3.select(this).attr("stroke", "#667eea").attr("stroke-width", 3);
                    })
                    .on("mouseout", function() {
                        d3.select(this).attr("stroke", "#999").attr("stroke-width", 2);
                    });

                linkLabel = g.append("g")
                    .selectAll("text")
                    .data(links)
                    .join("text")
                    .attr("font-size", 10)
                    .attr("fill", "#666")
                    .style("pointer-events", "none")
                    .style("user-select", "none")
                    .text(d => d.label);

                node = g.append("g")
                    .selectAll("g")
                    .data(nodes)
                    .join("g")
                    .style("cursor", "move")
                    .call(d3.drag()
                        .on("start", dragstarted)
                        .on("drag", dragged)
                        .on("end", dragended))
                    .on("dblclick", fixNode);

                node.append("circle")
                    .attr("r", 40)
                    .attr("fill", d => {
                        if (d.type === 'dimension') return '#e3f2fd';
                        if (d.type === 'fact') return '#fff3e0';
                        return '#f3e5f5';
                    })
                    .attr("stroke", d => {
                        if (d.type === 'dimension') return '#1976d2';
                        if (d.type === 'fact') return '#f57c00';
                        return '#7b1fa2';
                    })
                    .attr("stroke-width", 3);

                node.append("text")
                    .attr("text-anchor", "middle")
                    .attr("dy", -5)
                    .attr("font-size", 12)
                    .attr("font-weight", "bold")
                    .style("pointer-events", "none")
                    .text(d => d.id);

                node.append("text")
                    .attr("text-anchor", "middle")
                    .attr("dy", 10)
                    .attr("font-size", 10)
                    .attr("fill", "#666")
                    .style("pointer-events", "none")
                    .text(d => d.columns + " cols");

                simulation.on("tick", () => {
                    link.attr("d", d => {
                        return `M${d.source.x},${d.source.y} L${d.target.x},${d.target.y}`;
                    });

                    linkLabel
                        .attr("x", d => (d.source.x + d.target.x) / 2)
                        .attr("y", d => (d.source.y + d.target.y) / 2);

                    node.attr("transform", d => `translate(${d.x},${d.y})`);
                });

                setTimeout(() => fitToScreen(), 500);
            }

            function dragstarted(event) {
                if (!event.active) simulation.alphaTarget(0.3).restart();
                event.subject.fx = event.subject.x;
                event.subject.fy = event.subject.y;
            }

            function dragged(event) {
                event.subject.fx = event.x;
                event.subject.fy = event.y;
            }

            function dragended(event) {
                if (!event.active) simulation.alphaTarget(0);
            }

            function fixNode(event, d) {
                if (d.fx === null) {
                    d.fx = d.x;
                    d.fy = d.y;
                } else {
                    d.fx = null;
                    d.fy = null;
                }
            }

            window.resetZoom = function() {
                if (!svg) return;
                svg.transition().duration(750).call(
                    d3.zoom().transform,
                    d3.zoomIdentity
                );
            };

            window.fitToScreen = function() {
                if (!g) return;
                const bounds = g.node().getBBox();
                if (bounds.width === 0 || bounds.height === 0) return;
                
                const fullWidth = width;
                const fullHeight = height;
                const midX = bounds.x + bounds.width / 2;
                const midY = bounds.y + bounds.height / 2;
                const scale = 0.8 / Math.max(bounds.width / fullWidth, bounds.height / fullHeight);
                const translate = [fullWidth / 2 - scale * midX, fullHeight / 2 - scale * midY];

                svg.transition().duration(750).call(
                    d3.zoom().transform,
                    d3.zoomIdentity.translate(translate[0], translate[1]).scale(scale)
                );
            };

            window.toggleLabels = function() {
                labelsVisible = !labelsVisible;
                if (linkLabel) linkLabel.style("opacity", labelsVisible ? 1 : 0);
            };

            window.centerGraph = function() {
                if (!simulation) return;
                simulation.force("center", d3.forceCenter(width / 2, height / 2));
                simulation.alpha(0.3).restart();
            };

            let resizeTimer;
            window.addEventListener('resize', () => {
                clearTimeout(resizeTimer);
                resizeTimer = setTimeout(() => {
                    initDiagram();
                }, 250);
            });

            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', initDiagram);
            } else {
                initDiagram();
            }
        })();
    </script>

    </div>

Instruções de Uso
-----------------

Interações
~~~~~~~~~~

* 🖱️ **Arrastar:** Clique e arraste os nós para reorganizar o layout
* 🔍 **Zoom:** Use scroll do mouse para zoom in/out  
* 📌 **Fixar:** Duplo clique em um nó para fixá-lo na posição
* 🎯 **Hover:** Passe o mouse sobre links para destacá-los

Controles
~~~~~~~~~

* 🔄 **Reset Zoom** - Restaura zoom para 100%
* 📐 **Ajustar Tela** - Centraliza e ajusta todo o diagrama na tela
* 🏷️ **Toggle Labels** - Mostra/oculta labels dos relacionamentos
* 🎯 **Centralizar** - Reaplica força de centralização

Cores
~~~~~

* 🔵 **Azul** - Tabelas Dimensão (D_*)
* 🟠 **Laranja** - Tabelas Fato (F_*)  
* 🟣 **Roxo** - Outras Tabelas

Dicas
~~~~~

* Organize dimensões ao redor dos fatos para melhor visualização
* Use duplo clique para fixar nós importantes e organizar ao redor
* O diagrama é totalmente responsivo e se ajusta ao tamanho da tela
