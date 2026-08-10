"""Helpers to make curvilinear NetCDF outputs tile-friendly for rio-tiler."""

import rioxarray  # noqa: F401  (registers the .rio accessor)
import xarray as xr
from config import VARIABLES
from pyproj import CRS, Transformer


def needs_coordinate_reconstruction(
    ds: xr.Dataset,
    variable: str,
    grid_mapping_var: str = "crs",
) -> bool:
    """Return ``True`` if a datacube variable needs its 1D coords reconstructed.
    Datacube assets fall into three cases with respect to rio-tiler's XArray
    reader, which derives an affine transform strictly from 1D dimension
    coordinates and ignores any 2D coordinate arrays:
    * **Case A — already tileable.** The variable exposes 1D projected or
      geographic coordinates that describe a regular affine grid. rio-tiler can
      place and tile it as-is. ``needs_coordinate_reconstruction`` returns
      ``False`` (nothing to fix).
      Example: a Daymet NetCDF whose ``x``/``y`` dimensions carry 1D arrays of
      Lambert Azimuthal metres, or an ERA5 grid with 1D ``longitude``/
      ``latitude`` degree coordinates.
    * **Case B — recoverable, handled here.** The variable is gridded on plain
      integer index dimensions while its true geographic location is carried
      only by 2D ``latitude``/``longitude`` arrays (plus a CF grid mapping). The
      underlying grid is still regular in its projection, so the 1D projected
      coordinates can be reconstructed (see
      ``reconstruct_projected_coordinates``). This function returns ``True``.
      Example: ``conus_sample.nc`` — a regular 6 km Lambert Conformal Conic grid
      that shipped 2D ``latitude(y, x)``/``longitude(y, x)`` plus 0..N-1 integer
      ``x``/``y`` index dims instead of 1D projected coordinates.
    * **Case C — genuinely irregular / curvilinear.** The grid is not regular in
      any projection (e.g. a swath or warped grid), so no 1D affine coordinates
      exist. This cannot be repaired by reconstructing 1D coords and is
      unsupported by the XArray reader (it would require GCPs or a geolocation
      array, which rio-tiler does not pass through). This function returns
      ``False`` because no 2D-to-1D reconstruction would be valid.
      Example: a satellite swath product (e.g. VIIRS/MODIS L2) whose 2D lat/lon
      arrays follow the sensor's curved scan path, or an ocean model on a
      rotated/displaced-pole curvilinear grid (e.g. ORCA), where rows and
      columns are not constant-latitude/longitude lines.
    Returns ``False`` for Case A (already exposes 1D coordinates) and for the
    Case C / missing-data situations where no 2D lat/lon arrays are available to
    reconstruct from. Note that this regularity-based detection cannot, on its
    own, distinguish a truly regular Case B grid from a Case C grid that merely
    happens to ship 2D lat/lon over index dims; callers that may encounter Case
    C should validate grid regularity before relying on the reconstruction.
    """
    if grid_mapping_var not in ds.variables:
        return False

    # Need 2D lat/lon coordinate arrays to reconstruct projected coordinates.
    has_2d_lonlat = all(
        name in ds.coords and ds.coords[name].ndim == 2
        for name in ("longitude", "latitude")
    )
    if not has_2d_lonlat:
        return False

    # If a spatial dim already carries a non-trivial 1D coordinate (i.e. not a
    # plain 0..N-1 index range), rio-tiler can already place the data.
    def is_index_like(dim: str) -> bool:
        if dim not in ds.coords:
            return True
        values = ds.coords[dim].values
        return np.array_equal(values, np.arange(values.size))

    y_dim, x_dim = ds[variable].dims[-2], ds[variable].dims[-1]
    return is_index_like(str(x_dim)) and is_index_like(str(y_dim))


def reconstruct_projected_coordinates(
    ds: xr.Dataset,
    variable: str | list[str] = VARIABLES,
    grid_mapping_var: str = "crs",
) -> xr.Dataset:
    """Repair a "Case B" datacube by reconstructing 1D projected coordinates.
    Reconstructs 1D projected ``x``/``y`` coordinates (in metres) from the 2D
    ``latitude``/``longitude`` arrays and the CF grid mapping, writes a proper
    CRS + ``GeoTransform``, and drops the now-redundant 2D coordinate arrays.
    The grid is regular in its projection, so averaging each 2D coordinate over
    its orthogonal axis collapses it to a clean, monotonic 1D coordinate.
    ``variable`` may be a single name or a list of names that share the same
    spatial grid; all listed variables are reprojected onto the reconstructed
    1D coordinates.
    Returns a new dataset (with the listed variables) that the XArray reader can
    place and tile as a normal affine datacube.
    """
    variables = [variable] if isinstance(variable, str) else variable

    crs = CRS.from_cf(ds[grid_mapping_var].attrs)
    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    proj_x, proj_y = transformer.transform(
        ds["longitude"].values, ds["latitude"].values
    )
    x_1d = proj_x.mean(axis=0)
    y_1d = proj_y.mean(axis=1)

    y_dim, x_dim = str(ds[variables[0]].dims[-2]), str(ds[variables[0]].dims[-1])
    fixed = (
        ds[variables]
        .assign_coords({x_dim: (x_dim, x_1d), y_dim: (y_dim, y_1d)})
        .drop_vars(["latitude", "longitude"])
        .rio.write_crs(crs)
        .rio.set_spatial_dims(x_dim=x_dim, y_dim=y_dim)
        .rio.write_coordinate_system()
        .rio.write_transform()
    )
    return fixed
