from typing import Dict, Sequence, Any, Optional
import numpy as np
from pint import UnitRegistry
from collections import OrderedDict
import json


def load_json_ordered(filename: str) -> OrderedDict:
    """Loads json file as an ordered dict.
    Args:
        filename: Path to json file to be loaded.
    Returns:
        OrderedDict: odict
            OrderedDict containing data from json file.
    """
    with open(filename) as f:
        odict = json.load(f, object_pairs_hook=OrderedDict)
    return odict


def set_h5_attrs(g, kwargs):
    """Adds data to HDF5 group `g` from dict `kwargs`."""
    for name, value in kwargs.items():
        if isinstance(value, dict):
            sub_g = g.create_group(name)
            set_h5_attrs(sub_g, value)
        else:
            if isinstance(value, np.ndarray):
                g.create_dataset(name, data=value)
            else:
                g.attrs[name] = value


def make_scan_vectors(
    scan_params: Dict[str, Any], ureg: Any
) -> Dict[str, Sequence[float]]:
    """Creates x and y vectors for given scan parameters.

    Args:
        scan_params: Scan parameter dict
        ureg: pint UnitRegistry, manages units.

    Returns:
        Dict: scan_vectors
            {axis_name: axis_vector} for x, y axes.
    """
    Q_ = ureg.Quantity
    center = []
    size = []
    rng = []
    for ax in ["x", "y"]:
        center.append(Q_(scan_params["center"][ax]).to("V").magnitude)
        size.append(scan_params["scan_size"][ax])
        rng.append(Q_(scan_params["range"][ax]).to("V").magnitude)
    x = np.linspace(center[0] - 0.5 * rng[0], center[0] + 0.5 * rng[0], size[0])
    y = np.linspace(center[1] - 0.5 * rng[1], center[1] + 0.5 * rng[1], size[1])
    return {"x": x, "y": y}


def make_xy_grids(
    scan_vectors: Dict[str, Sequence[float]], slow_ax: str, fast_ax: str
) -> Dict[str, Any]:
    """Makes meshgrids from x, y scan_vectors (used for plotting, etc.).

    Args:
        scan_vectors: Dict of {axis_name: axis_vector} for x, y axes (from make_scan_vectors).
        slow_ax: Name of scan slow axis ('x' or 'y').
        fast_ax: Name of scan fast axis ('x' or 'y').

    Returns:
        Dict: xy_grids
            {axis_name: axis_grid} for x, y axes.
    """
    slow_ax_vec = scan_vectors[slow_ax]
    fast_ax_vec = scan_vectors[fast_ax]
    if fast_ax == "y":
        X, Y = np.meshgrid(slow_ax_vec, fast_ax_vec, indexing="ij")
    else:
        X, Y = np.meshgrid(fast_ax_vec, slow_ax_vec, indexing="xy")
    return {"x": X, "y": Y}


def to_real_units(data_set: Any, ureg: Any = None) -> Any:
    """Converts DataSet arrays from DAQ voltage to real units using recorded metadata.
        Preserves shape of DataSet arrays.

    Args:
        data_set: qcodes DataSet created by Microscope.scan_plane
        ureg: Pint UnitRegistry. Default None.

    Returns:
        np.ndarray: data
            ndarray like the DataSet array, but in real units as prescribed by
            factors in DataSet metadata.
    """
    if ureg is None:
        from pint import UnitRegistry

        ureg = UnitRegistry()
        ureg.define("Phi0 = Phi_0")
        ureg.define("Ohm = ohm")
    meta = data_set.metadata["loop"]["metadata"]
    data = np.full_like(data_set.daq_ai_voltage, np.nan, dtype=np.double)
    for i, ch in enumerate(meta["channels"].keys()):
        array = data_set.daq_ai_voltage[:, i, :] * ureg("V")
        unit = meta["channels"][ch]["unit"]
        data[:, i, :] = (array * ureg.Quantity(meta["prefactors"][ch])).to(unit)
    return data


def scan_to_arrays(
    scan_data: Any,
    ureg: Optional[Any] = None,
    real_units: Optional[bool] = True,
    xy_unit: Optional[str] = None,
) -> Dict[str, Any]:
    """Extracts scan data from DataSet and converts to requested units.

    Args:
        scan_data: qcodes DataSet created by Microscope.scan_plane
        ureg: pint UnitRegistry, manages physical units.
        real_units: If True, converts z-axis data from DAQ voltage into
            units specified in measurement configuration file.
        xy_unit: String describing quantity with dimensions of length.
            If xy_unit is not None, scanner x, y DAQ ao voltage will be converted to xy_unit
            according to scanner constants defined in microscope configuration file.

    Returns:
        Dict: arrays
            Dict of x, y vectors and grids, and measured data in requested units.
    """
    if ureg is None:
        from pint import UnitRegistry

        ureg = UnitRegistry()
        ureg.define("Phi0 = Phi_0")
        ureg.define("Ohm = ohm")
    Q_ = ureg.Quantity
    meta = scan_data.metadata["loop"]["metadata"]
    scan_vectors = make_scan_vectors(meta, ureg)
    slow_ax = "x" if meta["fast_ax"] == "y" else "y"
    grids = make_xy_grids(scan_vectors, slow_ax, meta["fast_ax"])
    arrays = {"X": grids["x"] * ureg("V"), "Y": grids["y"] * ureg("V")}
    arrays.update(
        {"x": scan_vectors["x"] * ureg("V"), "y": scan_vectors["y"] * ureg("V")}
    )
    for ch, info in meta["channels"].items():
        array = scan_data.daq_ai_voltage[:, info["idx"], :] * ureg("V")
        if meta["fast_ax"] == "y":
            array = array.T
        if real_units:
            pre = meta["prefactors"][ch]
            arrays.update({ch: (Q_(pre) * array).to(info["unit"])})
        else:
            arrays.update({ch: array})
    if real_units and xy_unit is not None:
        bendc = scan_data.metadata["station"]["instruments"]["benders"]["metadata"][
            "constants"
        ]
        for ax in ["x", "y"]:
            grid = (grids[ax] * ureg("V") * Q_(bendc[ax])).to(xy_unit)
            vector = (scan_vectors[ax] * ureg("V") * Q_(bendc[ax])).to(xy_unit)
            arrays.update({ax.upper(): grid, ax: vector})
    return arrays


def td_to_arrays(
    td_data: Any,
    ureg: Optional[Any] = None,
    real_units: Optional[bool] = True,
    z_unit: Optional[str] = None,
) -> Dict[str, Any]:
    """Extracts scan data from DataSet and converts to requested units.

    Args:
        td_data: qcodes DataSet created by Microscope.td_cap
        ureg: pint UnitRegistry, manages physical units.
        real_units: If True, converts data from DAQ voltage into
            units specified in measurement configuration file.
        z_unit: String describing quantity with dimensions of length.
            If z_unit is not None, scanner z DAQ ao voltage will be converted to z_unit
            according to scanner constant defined in microscope configuration file.
    Returns:
        Dict: arrays
            Dict of measured data in requested units.
    """
    if ureg is None:
        from pint import UnitRegistry

        ureg = UnitRegistry()
        ureg.define("Phi0 = Phi_0")
        ureg.define("Ohm = ohm")
    Q_ = ureg.Quantity
    meta = td_data.metadata["loop"]["metadata"]
    h = [Q_(val).to("V").magnitude for val in meta["range"]]
    dV = Q_(meta["dV"]).to("V").magnitude
    heights = np.linspace(h[0], h[1], int((h[1] - h[0]) / dV)) * ureg("V")
    arrays = {}
    # arrays = {'height': heights * ureg('V')}
    for ch, info in meta["channels"].items():
        array = td_data.daq_ai_voltage[:, info["idx"], 0] * ureg("V")
        last_idx = min(len(heights), len(array[np.isfinite(array)]))
        if real_units:
            pre = meta["prefactors"][ch]
            arrays.update({ch: (Q_(pre) * array[:last_idx]).to(info["unit"])})
        else:
            arrays.update({ch: array[:last_idx]})
    if real_units and z_unit is not None:
        bendc = td_data.metadata["station"]["instruments"]["benders"]["metadata"][
            "constants"
        ]
        heights = (heights * Q_(bendc["z"])).to(z_unit)
    arrays.update({"height": heights[:last_idx]})
    return arrays
