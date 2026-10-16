require "test_helper"

class ImportmapTest < ActiveSupport::TestCase
  def imports
    JSON.parse(Rails.application.importmap.to_json(resolver: ApplicationController.helpers))["imports"]
  end

  test "preloaded_module_paths excludes chart controllers and d3 modules" do
    preloaded = Rails.application.importmap.preloaded_module_paths(
      resolver: ApplicationController.helpers
    )
    chart_paths = preloaded.grep(%r{d3-|internmap|^charts/})
    assert_empty chart_paths, "preload pulls these on every page regardless of lazy registration"
  end

  test "chart controllers are pinned under charts and not under controllers" do
    assert_empty imports.keys.grep(%r{^controllers/(chart|funnel|hbars|lorenz|parts|ring|scatter|treemap)_controller$}),
      "eagerLoadControllersFrom('controllers') fetches everything it finds under that prefix"
    assert_equal %w[charts/chart_controller charts/export charts/frame
                    charts/funnel_controller charts/gesture
                    charts/hbars_controller charts/lorenz_controller
                    charts/overview charts/parts_controller charts/ring_controller
                    charts/scatter_controller charts/squarify charts/tiles
                    charts/treemap_controller],
      imports.keys.grep(%r{^charts/}).sort
  end

  test "lazy registration pattern excludes charts modules that are not controllers" do
    index = Rails.root.join("app/javascript/controllers/index.js").read
    pattern = index[/\/\^charts\\\/\.\*_controller\$\//]
    assert pattern, "the lazy registration pattern moved"
    assert_no_match(/_controller$/, "charts/squarify",
      "squarify is a plain module, so the registration pattern must skip it")
  end

  test "index.js loads charts lazily and other controllers eagerly" do
    index = Rails.root.join("app/javascript/controllers/index.js").read
    assert_includes index, %(eagerLoadControllersFrom("controllers", application))
    assert_no_match(/eagerLoadControllersFrom\(\s*"charts"/, index,
      "charts depend on d3 and must not load on pages without charts")
    assert_match(/\^charts\\\/\.\*_controller\$/, index,
      "the lazy registration must find its candidates in the charts namespace")
    assert_no_match(/lazyLoadControllersFrom/, index,
      "the prefix loader tries charts/<name>_controller for every identifier on the page")
  end

  test "every chart identifier used in a view resolves to a pinned charts module" do
    used = Dir[Rails.root.join("app/views/**/*.erb")].flat_map { |f|
      File.read(f).scan(/data-controller="([^"]*)"/).flatten
    }.flat_map(&:split).uniq & %w[chart hbars lorenz parts scatter treemap]
    assert_equal %w[chart lorenz parts scatter treemap], used.sort,
      "a chart identifier moved or was removed"
    used.each do |name|
      assert imports.key?("charts/#{name}_controller"),
        "data-controller=\"#{name}\" would lazy load charts/#{name}_controller, which is not pinned"
    end
  end
end
