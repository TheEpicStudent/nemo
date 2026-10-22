module LandingHelper
  REPOSITORY_URL = "https://github.com/hackclub/nemo".freeze
  HACK_CLUB_URL = "https://hackclub.com".freeze

  HACK_CLUB_GLYPH = "M115.103 48.3682C115.103 47.1299 113.989 46.1892 112.769 46.3965L81.6652 " \
    "51.6777C80.7036 51.8409 80 52.6741 80 53.6494V205.085C80 206.189 80.8954 207.085 82 " \
    "207.085H113.103C114.208 207.085 115.103 206.189 115.103 205.085V148.397C115.103 131.127 " \
    "124.261 120.429 131.892 120.429C138.76 120.429 140.744 127.307 140.744 137.699V205.085C140.744 " \
    "206.189 141.639 207.085 142.744 207.085H174C175.105 207.085 176 206.189 176 " \
    "205.085V132.656C176 109.12 167.148 93.9892 144.102 93.9892C134.852 93.9892 125.825 96.2163 " \
    "118.633 101.146C117.205 102.125 115.103 101.161 115.103 99.4284V48.3682Z".freeze

  GITHUB_MARK = "M12 .5C5.65.5.5 5.65.5 12a11.5 11.5 0 0 0 7.86 10.92c.58.1.79-.25.79-.56v-2c-3.2.7-3.87-1.37" \
    "-3.87-1.37-.52-1.33-1.28-1.69-1.28-1.69-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 " \
    "2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.68 0-1.26.45-2.28 1.19-3.09-.12-.29" \
    "-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 " \
    "2.76.11 3.05.74.81 1.19 1.83 1.19 3.09 0 4.41-2.69 5.39-5.25 5.67.41.36.78 1.06.78 2.14v3.17c0 " \
    ".31.21.67.8.56A11.5 11.5 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5Z".freeze

  ARROW = ["M5 12h14", "M13 6l6 6-6 6"].freeze

  NAV_LINKS = [["Features", "#features"], ["In the app", "#in-the-app"], ["API", "#api"]].freeze

  CASE_MESSAGES = [
    { name: "jana.c", tint: 2, time: "11 Oct, 14:02", role: "reporter",
      text: "he posted a cofounder ad in #hackathons and then dmed everyone who replied" },
    { name: "marisol", tint: 5, time: "11 Oct, 14:10", role: "reporter",
      text: "thanks for telling us. can you send the dm he sent you?" },
    { name: "aisha", tint: 3, time: "11 Oct, 14:30",
      text: "same dm to 9 people. warning and a channel ban from #hackathons." }
  ].freeze

  CASE_TABS = [["Report", 2], ["People", 2], ["Actions", 0], ["Notes", 1], ["Timeline", 5]].freeze

  NEMO_COMMANDS = [
    { name: "lookup", usage: "@member", example: "/nemo lookup @jana.c" },
    { name: "shush", usage: "@member 3d", example: "/nemo shush @devon 3d" },
    { name: "channelban", usage: "@member #channel 3d", example: "/nemo channelban @devon #hackathons 3d" },
    { name: "slowmode", usage: "#channel 30s 2h", example: "/nemo slowmode #lounge 30s 2h" },
    { name: "purge", usage: "#channel 50", example: "/nemo purge #lounge 50" }
  ].freeze

  ACTION_LABELS = ["Warning", "Shush", "Temporary ban", "Indefinite ban", "Permanent ban", "Channel ban",
    "Locked thread", "DM", "Deleted messages"].freeze

  SLACK_SHORTCUTS = [
    { label: "Report anonymously", icon: ["M4 21V4", "M4 4h12l-2 4 2 4H4"] },
    { label: "Lock thread", icon: ["M6 11h12v9H6z", "M8 11V8a4 4 0 0 1 8 0v3"] },
    { label: "Slow mode", icon: ["M12 8v4l2.5 2.5", "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18"] },
    { label: "Destroy thread", icon: ["M4 7h16", "M10 11v6", "M14 11v6", "M6 7l1 13h10l1-13", "M9 7V4h6v3"] },
    { label: "View message activity", icon: ["M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12",
      "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6"] }
  ].freeze

  API_REQUEST = "GET /api/v1/channels/:channel_id/managers/:user_id".freeze

  AUDIT_ROWS = [
    ["14:31", "devon", "Signed in"],
    ["14:29", "jana.c", "Failed to sign in"],
    ["14:12", "slack", "Unusual activity"],
    ["13:58", "marisol", "Sessions reset by an admin"],
    ["13:40", "aisha", "Channel archived"]
  ].freeze

  ACTIVE_SERIES = [62, 58, 64, 57, 52, 48, 53, 50, 45, 47, 42, 44, 41, 38, 43, 40, 36, 41, 45, 42, 39,
    35, 38, 34].freeze
  AREA_W = 300
  AREA_H = 72

  CLUSTER_NODES = [[24, 34], [60, 8], [96, 34], [60, 58, true]].freeze
  CLUSTER_LINKS = [[0, 1], [1, 2], [2, 3], [3, 0], [0, 2], [1, 3]].freeze

  HEADLINE_EFFECT = {
    splitType: "words", delay: 60, duration: 1.1, ease: "power3.out", threshold: 0, rootMargin: "0px",
    from: { opacity: 0, y: 28, filter: "blur(10px)" }, to: { opacity: 1, y: 0, filter: "blur(0px)" }
  }.freeze

  SPOTLIGHT_EFFECT = { spotlightColor: "#f08a45", intensity: 0.22, spotlightSize: 320, softness: 0.75,
    borderGlow: 0.8 }.freeze

  WAVES_EFFECT = { horizonColor: "#143252", waveColor: "#f08a45", crestColor: "#f5e3c3",
    speed: 0.3, amplitude: 2.2, swell: 30, lightAngle: 120, tilt: 52, height: 3.5, zoom: 1.2, grain: 0.15, brightness: 1.15, quality: "medium",
    swellOnClick: false, maxDevicePixelRatio: 1.5 }.freeze

  MAGNET_EFFECT ={ padding: 70, magnetStrength: 3, maxOffset: 8 }.freeze

  RAYS_EFFECT = { raysOrigin: "top-center", raysColor: "#f5e3c3", raysSpeed: 0.7, lightSpread: 0.85,
    rayLength: 1.7, intensity: 0.85, followMouse: true, mouseInfluence: 0.08, clickPulse: false,
    maxDevicePixelRatio: 1.5 }.freeze

  ACTION_LOOP = { speed: 36, gap: 10, logoHeight: 30, pauseOnHover: true, fadeOut: true,
    fadeOutWidth: 0.14, draggable: false, ariaLabel: "Action types" }.freeze

  GALLERY = [
    { capture: "community-overview", label: "Community overview", area: "Analytics", wide: true },
    { capture: "fd-case", label: "Case view", area: "Fire Engine" },
    { capture: "channels", label: "Channels", area: "Analytics" },
    { capture: "fd-clusters", label: "Alt account clusters", area: "Fire Engine", wide: true }
  ].freeze

  CAPTURE_WIDTHS = [1440, 2880].freeze
  CAPTURE_SIZES = "(max-width: 899px) 100vw, 60vw".freeze

  def landing_capture(name, alt)
    srcset = ->(format) { CAPTURE_WIDTHS.map { |w| "#{image_path("landing/#{name}-#{w}.#{format}")} #{w}w" }.join(", ") }
    tag.picture do
      concat tag.source(type: "image/avif", srcset: srcset.call("avif"), sizes: CAPTURE_SIZES)
      concat image_tag("landing/#{name}-1440.webp", srcset: srcset.call("webp"), sizes: CAPTURE_SIZES,
        alt: alt, width: 1440, height: 900, loading: "lazy", decoding: "async")
    end
  end

  def landing_area_path(values, closed: false)
    low, high = values.minmax
    step = AREA_W.to_f / (values.size - 1)
    points = values.each_with_index.map do |value, index|
      [(index * step).round(1), (AREA_H - 4 - ((value - low) * (AREA_H - 12) / (high - low).to_f)).round(1)]
    end
    line = "M#{points.map { |x, y| "#{x},#{y}" }.join(" L")}"
    closed ? "#{line} L#{AREA_W},#{AREA_H} L0,#{AREA_H} Z" : line
  end

  def effect_data(name, options)
    { controller: "effect", effect_name_value: name, effect_options_value: options.to_json }
  end

  def hack_club_mark
    tag.svg(class: "landing-hc-mark", viewBox: "0 0 256 256", "aria-hidden": "true") do
      concat tag.rect(width: 256, height: 256, rx: 64, class: "landing-hc-mark-tile")
      concat tag.path(d: HACK_CLUB_GLYPH, class: "landing-hc-mark-glyph")
    end
  end

  def github_mark
    tag.svg(class: "landing-gh-mark", viewBox: "0 0 24 24", "aria-hidden": "true") do
      tag.path(d: GITHUB_MARK, fill: "currentColor")
    end
  end

  def landing_icon(paths, size: 16)
    tag.svg(class: "landing-icon", width: size, height: size, viewBox: "0 0 24 24", fill: "none",
      stroke: "currentColor", "stroke-width": 1.7, "stroke-linecap": "round",
      "stroke-linejoin": "round", "aria-hidden": "true") do
      safe_join(paths.map { |d| tag.path(d: d) })
    end
  end

  def landing_arrow
    landing_icon(ARROW, size: 16)
  end
end
