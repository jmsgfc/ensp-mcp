from backend.topology.parser import parse_topology


def _topology_xml(name="设备1"):
    return f"""<?xml version="1.0" encoding="UNICODE"?>
<topo version="1.0">
  <devices>
    <dev id="1" name="{name}" model="S5700" com_port="2000">
      <slot>
        <interface sztype="GE" interfacename="GE" count="24" />
      </slot>
    </dev>
  </devices>
  <lines />
</topo>
"""


def test_declared_unicode_gb18030_file_still_parses(tmp_path):
    topo_path = tmp_path / "lab.topo"
    topo_path.write_bytes(_topology_xml().encode("gb18030"))

    topology = parse_topology(topo_path)

    assert topology.devices[0].name == "设备1"
    assert topology.devices[0].interfaces[0].count == 24
