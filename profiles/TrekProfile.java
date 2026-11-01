import com.onthegomap.planetiler.FeatureCollector;
import com.onthegomap.planetiler.FeatureMerge;
import com.onthegomap.planetiler.Planetiler;
import com.onthegomap.planetiler.Profile;
import com.onthegomap.planetiler.VectorTile;
import com.onthegomap.planetiler.config.Arguments;
import com.onthegomap.planetiler.reader.SourceFeature;
import com.onthegomap.planetiler.reader.osm.OsmElement;
import com.onthegomap.planetiler.reader.osm.OsmRelationInfo;
import java.nio.file.Path;
import java.util.List;

/**
 * Trekbuddy hiking overlay ("trek" tiles), drawn on top of the OpenMapTiles base map.
 *
 * <p>Layers:
 * <ul>
 *   <li>{@code hiking_route} (z9-14): ways of route=hiking relations, with the relation's
 *       name, ref, network, cai_scale, osmc:symbol and operator. A way shared by several
 *       relations is emitted once per relation.</li>
 *   <li>{@code trail} (z12-14): footpaths, tracks, steps and via ferratas with their difficulty
 *       and visibility, which the OpenMapTiles schema does not carry.</li>
 *   <li>{@code mountain_poi}: huts, bivouacs, drinking water, springs and parking.</li>
 *   <li>{@code contour} (z11-14): contour lines from {@code --contours_path} (GeoJSON made by
 *       pipeline/contours.py), with {@code ele} and {@code idx} (index contour every 100 m).</li>
 * </ul>
 *
 * <p>Run with the Planetiler jar on the classpath (Java 25, source-file mode):
 * {@code java -cp planetiler.jar profiles/TrekProfile.java --osm_path=<pbf> --output=trek.pmtiles
 * --bounds=<w,s,e,n> --minzoom=9 --maxzoom=14 [--contours_path=contours.geojson]}
 */
public class TrekProfile implements Profile {

  private record HikingRoute(
    @Override long id,
    String name, String ref, String network, String caiScale, String osmcSymbol, String operator
  ) implements OsmRelationInfo {}

  private record Poi(String kind, int minZoom) {}

  @Override
  public List<OsmRelationInfo> preprocessOsmRelation(OsmElement.Relation relation) {
    if (relation.hasTag("type", "route") && relation.hasTag("route", "hiking")) {
      return List.of(new HikingRoute(
        relation.id(),
        relation.getString("name"),
        relation.getString("ref"),
        relation.getString("network"),
        relation.getString("cai_scale"),
        relation.getString("osmc:symbol"),
        relation.getString("operator")
      ));
    }
    return null;
  }

  @Override
  public void processFeature(SourceFeature feature, FeatureCollector features) {
    if (feature.getSource().equals("contours")) {
      long ele = feature.getLong("ele");
      // Contour interval per zoom (Fase 5): 100 m from z11, 50 m from z12, 20 m from z13, 10 m at z14.
      int minZoom = ele % 100 == 0 ? 11 : ele % 50 == 0 ? 12 : ele % 20 == 0 ? 13 : 14;
      features.line("contour")
        .setAttr("ele", ele)
        .setAttr("idx", ele % 100 == 0) // index contour, drawn bolder
        // DEM contours have a vertex every pixel; a coarser simplification trims about a tenth
        // of the file without a visible change.
        .setPixelTolerance(0.5)
        .setZoomRange(minZoom, 14);
      return;
    }
    if (feature.canBeLine()) {
      for (var member : feature.relationInfo(HikingRoute.class)) {
        HikingRoute route = member.relation();
        features.line("hiking_route")
          .setAttr("relation_id", route.id())
          .setAttr("name", route.name())
          .setAttr("ref", route.ref())
          .setAttr("network", route.network())
          .setAttr("cai_scale", route.caiScale())
          .setAttr("osmc_symbol", route.osmcSymbol())
          .setAttr("operator", route.operator())
          .setZoomRange(9, 14)
          .setMinPixelSize(0);
      }
      if (feature.hasTag("highway", "path", "footway", "track", "steps", "bridleway", "via_ferrata")
        && !feature.hasTag("footway", "sidewalk", "crossing")) {
        features.line("trail")
          .setAttr("highway", feature.getString("highway"))
          .setAttr("sac_scale", feature.getString("sac_scale"))
          .setAttr("trail_visibility", feature.getString("trail_visibility"))
          .setAttr("surface", feature.getString("surface"))
          .setAttr("name", feature.getString("name"))
          .setZoomRange(12, 14)
          .setMinPixelSize(0);
      }
    }

    Poi poi = poi(feature);
    if (poi != null) {
      var point = feature.isPoint() ? features.point("mountain_poi")
        : feature.canBePolygon() ? features.pointOnSurface("mountain_poi") : null;
      if (point != null) {
        point.setAttr("kind", poi.kind())
          .setAttr("osm_id", feature.id())
          .setAttr("name", feature.getString("name"))
          .setAttr("ele", feature.getString("ele"))
          .setAttr("opening_hours", feature.getString("opening_hours"))
          .setAttr("capacity", feature.getString("capacity"))
          .setAttr("operator", feature.getString("operator"))
          .setAttr("drinking_water", feature.getString("drinking_water"))
          .setZoomRange(poi.minZoom(), 14);
      }
    }
  }

  private static Poi poi(SourceFeature f) {
    if (f.hasTag("tourism", "alpine_hut")) return new Poi("alpine_hut", 10);
    if (f.hasTag("tourism", "wilderness_hut")) return new Poi("wilderness_hut", 11);
    if (f.hasTag("amenity", "drinking_water")) return new Poi("drinking_water", 13);
    if (f.hasTag("natural", "spring")) return new Poi("spring", 13);
    if (f.hasTag("amenity", "parking") && !f.hasTag("access", "private", "no", "customers")) {
      return new Poi("parking", 13);
    }
    return null;
  }

  @Override
  public List<VectorTile.Feature> postProcessLayerFeatures(String layer, int zoom,
    List<VectorTile.Feature> items) {
    if (layer.equals("mountain_poi")) {
      return items;
    }
    // Joins touching segments with the same attributes (one relation, one trail type) so the
    // style can place one label per route instead of one per OSM way.
    return FeatureMerge.mergeLineStrings(items, 0.5, 0.1, 4);
  }

  @Override
  public String name() {
    return "Trekbuddy trek";
  }

  @Override
  public String description() {
    return "Hiking routes, trail difficulty, mountain points of interest and contour lines";
  }

  @Override
  public boolean isOverlay() {
    return true;
  }

  @Override
  public String attribution() {
    return "<a href=\"https://www.openstreetmap.org/copyright\" target=\"_blank\">&copy; OpenStreetMap contributors</a>";
  }

  public static void main(String[] args) throws Exception {
    Arguments arguments = Arguments.fromArgsOrConfigFile(args);
    Path osm = arguments.inputFile("osm_path", "OSM input file", Path.of("work/osm/build.osm.pbf"));
    Path output = arguments.file("output", "output file", Path.of("trek.pmtiles"));
    String contours = arguments.getString("contours_path", "GeoJSON contour lines (pipeline/contours.py)", "");
    Planetiler planetiler = Planetiler.create(arguments)
      .setProfile(new TrekProfile())
      .addOsmSource("osm", osm);
    if (!contours.isEmpty()) {
      planetiler.addGeoJsonSource("contours", Path.of(contours));
    }
    planetiler.overwriteOutput(output).run();
  }
}
