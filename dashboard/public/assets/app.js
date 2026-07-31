/* Thailand Ocean Logistics Intelligence — static dashboard renderer.
 *
 * No framework, no external script, no network call beyond the JSON files
 * this same build produced. Every chart is accompanied by a table with the
 * identical numbers, and every missing period is rendered as a stated gap
 * rather than as a zero.
 *
 * If a payload fails to load the section says so and the coverage banner
 * stays at its most pessimistic reading. A dashboard that silently renders
 * an empty panel is worse than one that admits it could not load.
 *
 * Seven views live under one document (WO-030): a hash router shows exactly
 * one <section class="view"> at a time via the `hidden` attribute, all eight
 * payloads are still fetched eagerly and in parallel so a failure in a view
 * nobody has visited is still caught, but each view's markup is only built
 * the first time it becomes active.
 */
(function () {
  'use strict';

  var DIRECTION_PILL = {
    improving: 'pill-ok',
    stable: 'pill-note',
    deteriorating: 'pill-critical',
    mixed: 'pill-warning',
    insufficient_evidence: 'pill-muted'
  };
  var ATTENTION_PILL = {
    routine: 'pill-ok',
    watch: 'pill-warning',
    elevated: 'pill-critical',
    insufficient_evidence: 'pill-muted'
  };
  var FRESHNESS_PILL = {
    fresh: 'pill-ok',
    stale: 'pill-warning',
    very_stale: 'pill-critical',
    no_data: 'pill-muted',
    disabled: 'pill-muted',
    error: 'pill-critical',
    /* Fixture statuses are deliberately disjoint from the real-world set: a
       generated number has no publisher to have fallen behind. */
    fixture_not_live: 'pill-demo',
    historical_validation: 'pill-demo',
    not_applicable: 'pill-muted'
  };

  var DEMO_LABEL = {
    technical_demo: 'Technical demonstration — synthetic fixture',
    historical_validation: 'Historical validation — not a current condition'
  };

  /* Every panel built from fixture data is labelled individually. A reader who
     lands mid-page, follows a deep link, or prints one section must still see
     that what they are looking at is not current intelligence. */
  function demoTag(dataset) {
    if (!DEMO_LABEL[dataset]) return '';
    return '<span class="pill pill-demo">' + esc(DEMO_LABEL[dataset]) + '</span>';
  }

  var STATUS_PILL = {
    observed: 'pill-critical',
    potential: 'pill-warning',
    no_material: 'pill-ok',
    insufficient_evidence: 'pill-muted'
  };

  function esc(value) {
    return String(value === null || value === undefined ? '' : value).replace(
      /[&<>'"]/g,
      function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c];
      }
    );
  }

  /* Single escaping helper for every attribute value this file emits (ids,
     aria-controls references, data-* values, hrefs after the scheme check
     below). Text-content escaping uses the same rules, so attr() is esc()
     under another name — the point is that every attribute site names this
     function, not that the algorithm differs. */
  function attr(value) { return esc(value); }

  /* URL-scheme allowlist, checked before any href is ever emitted. A claim
     string in a JSON payload is untrusted input as far as this file is
     concerned; a `javascript:` or `data:` URL must never reach an <a href>.
     Returns '' (render no link) for anything outside the allowlist. */
  function safeHref(url) {
    if (!url) return '';
    var trimmed = String(url).trim();
    var scheme = /^([a-zA-Z][a-zA-Z0-9+.-]*):/.exec(trimmed);
    if (scheme && ['http', 'https', 'mailto'].indexOf(scheme[1].toLowerCase()) === -1) {
      return '';
    }
    return attr(trimmed);
  }

  function externalLink(url, label) {
    var href = safeHref(url);
    if (!href) return '';
    return ' · <a href="' + href + '" rel="noopener noreferrer" target="_blank">' + esc(label || 'source') + '</a>';
  }

  function el(id) { return document.getElementById(id); }

  function words(value) {
    return String(value || '').replace(/_/g, ' ');
  }

  function pill(value, map, extra) {
    var cls = (map && map[value]) || 'pill-muted';
    return '<span class="pill ' + cls + '">' + esc(words(value)) + esc(extra || '') + '</span>';
  }

  /* A number, or an explicit statement that there is no number. Never 0. */
  function num(value, digits) {
    if (value === null || value === undefined) {
      return '<span class="missing">not available</span>';
    }
    var fixed = Number(value);
    if (!isFinite(fixed)) return '<span class="missing">not available</span>';
    return esc(fixed.toLocaleString(undefined, {
      minimumFractionDigits: digits === undefined ? 0 : digits,
      maximumFractionDigits: digits === undefined ? 2 : digits
    }));
  }

  function pct(value) {
    if (value === null || value === undefined) {
      return '<span class="missing">not computable</span>';
    }
    var sign = value > 0 ? '+' : '';
    return esc(sign + Number(value).toFixed(2) + '%');
  }

  function list(items, emptyText) {
    if (!items || !items.length) {
      return '<p class="empty-state">' + esc(emptyText || 'None recorded.') + '</p>';
    }
    return '<ul class="prose-list">' + items.map(function (item) {
      return '<li>' + esc(item) + '</li>';
    }).join('') + '</ul>';
  }

  function detailsBlock(summary, body) {
    return '<details><summary>' + esc(summary) + '</summary>' +
      '<div class="details-body">' + body + '</div></details>';
  }

  function freshnessCell(freshness) {
    if (!freshness) return pill('no_data', FRESHNESS_PILL);
    var age = freshness.age_days === null || freshness.age_days === undefined
      ? 'age unknown'
      : freshness.age_days + ' days old';
    return pill(freshness.status, FRESHNESS_PILL) + ' <small>' + esc(age) + '</small>';
  }

  /* ---------------- charts ---------------- */

  /* Draws a sparkline in which missing periods are visible breaks, plus a
     text line of min/max/latest/period-range/gap-count so the same reading
     the chart shows is also available as text (WCAG 1.1.1, AC-22). The same
     numbers are always rendered as a table alongside via pointsTable(), so
     the chart is never the only way to read the series. */
  function sparkline(points) {
    var usable = points.filter(function (p) { return p.value !== null && p.value !== undefined; });
    if (usable.length < 2) {
      return '<p class="empty-state">Not enough usable observations to draw a chart. ' +
        'Missing periods are not plotted as zero.</p>';
    }
    var width = 640, height = 120, padX = 6, padY = 10;
    var values = usable.map(function (p) { return p.value; });
    var min = Math.min.apply(null, values), max = Math.max.apply(null, values);
    var span = (max - min) || 1;
    var stepX = (width - padX * 2) / (points.length - 1 || 1);

    var segments = [], current = [];
    points.forEach(function (point, index) {
      if (point.value === null || point.value === undefined) {
        if (current.length) { segments.push(current); current = []; }
        return;
      }
      var x = padX + index * stepX;
      var y = height - padY - ((point.value - min) / span) * (height - padY * 2);
      current.push([x, y]);
    });
    if (current.length) segments.push(current);

    var paths = segments.map(function (segment) {
      return '<path class="line" d="M' + segment.map(function (p) {
        return p[0].toFixed(1) + ' ' + p[1].toFixed(1);
      }).join(' L') + '"/>';
    }).join('');

    var lastPoint = segments.length ? segments[segments.length - 1].slice(-1)[0] : null;
    var dot = lastPoint
      ? '<circle class="dot" cx="' + lastPoint[0].toFixed(1) + '" cy="' + lastPoint[1].toFixed(1) + '" r="3"/>'
      : '';

    var gapCount = points.length - usable.length;
    var label = 'Sparkline of ' + usable.length + ' usable observations' +
      (gapCount ? ', with ' + gapCount + ' missing period(s) shown as breaks in the line' : '') +
      '. The full numbers are in the table below.';

    var svg = '<svg class="chart" viewBox="0 0 ' + width + ' ' + height + '" preserveAspectRatio="none" ' +
      'role="img" aria-label="' + esc(label) + '">' + paths + dot + '</svg>';

    var latest = usable[usable.length - 1];
    var scale = '<p class="chart-scale">Min ' + num(min, 2) + ' · Max ' + num(max, 2) + ' · Latest ' +
      num(latest.value, 2) + ' (' + esc(latest.period) + ') · ' + esc(points[0].period) + '–' +
      esc(points[points.length - 1].period) + ' · ' + points.length + ' periods, ' + gapCount +
      ' missing (drawn as breaks, never as zero)</p>';

    return svg + scale;
  }

  function pointsTable(points, unit) {
    var rows = points.map(function (point) {
      var cell = point.value === null || point.value === undefined
        ? '<td class="num missing">' + esc(words(point.value_status)) + ' — not zero</td>'
        : '<td class="num">' + num(point.value, 2) + '</td>';
      return '<tr><th scope="row">' + esc(point.period) + '</th>' + cell + '</tr>';
    }).join('');
    return '<div class="table-wrap"><table>' +
      '<caption>Every period in the series, including periods with no published value. ' +
      'A missing period is stated as missing and is never counted as zero.</caption>' +
      '<thead><tr><th scope="col">Period</th><th scope="col" class="num">Value' +
      (unit ? ' (' + esc(unit) + ')' : '') + '</th></tr></thead><tbody>' + rows +
      '</tbody></table></div>';
  }

  function seriesBlock(series, title, metaLines) {
    var provenance = [];
    if (series.source_id) {
      provenance.push('Source: ' + series.source_id);
    }
    if (series.intended_source_id) {
      provenance.push('Stands in for: ' + series.intended_source_id);
    }
    if (series.evidence_origin) {
      provenance.push('Origin: ' + words(series.evidence_origin));
    }
    var figures = [
      ['Latest value', num(series.current_value, 2) + (series.unit ? ' <small>' + esc(series.unit) + '</small>' : '')],
      ['Period', esc(series.current_period || 'none')],
      ['Month over month', pct(series.month_over_month_pct)],
      ['Year over year', pct(series.year_over_year_pct)],
      ['Rolling average', num(series.rolling_average, 2)],
      ['Deviation from baseline', series.baseline_definition ? num(series.deviation_from_baseline, 3) : '<span class="missing">no baseline defined</span>'],
      ['Periods used', esc(series.periods_available + ' of ' + series.periods_total)],
      ['Revision status', esc(words(series.revision_status))]
    ].map(function (pair) {
      return '<div class="figure"><div class="label">' + esc(pair[0]) + '</div>' +
        '<div class="value">' + pair[1] + '</div></div>';
    }).join('');

    var limitations = (series.limitations || []).concat(series.source_limitations || []);

    return '<div class="series' + (DEMO_LABEL[series.dataset] ? ' is-demo' : '') + '"' +
      (DEMO_LABEL[series.dataset] ? ' data-demo-label="' + attr(DEMO_LABEL[series.dataset]) + '"' : '') +
      '>' +
      '<h4>' + esc(title || series.series_id) + ' ' + demoTag(series.dataset) + '</h4>' +
      '<p class="series-meta">' + (metaLines || []).concat(provenance).map(esc).join(' · ') +
      ' · Freshness: ' + freshnessCell(series.freshness) + '</p>' +
      '<div class="series-figures">' + figures + '</div>' +
      sparkline(series.points || []) +
      detailsBlock('Show all ' + (series.points || []).length + ' periods as a table',
        pointsTable(series.points || [], series.unit)) +
      detailsBlock('Known limitations (' + limitations.length + ')', list(limitations, 'None recorded.')) +
      '</div>';
  }

  /* ---------------- loading ---------------- */

  function load(name) {
    return fetch('data/' + name).then(function (response) {
      if (!response.ok) throw new Error(name + ': HTTP ' + response.status);
      return response.json();
    });
  }

  function failSection(node, name, error) {
    if (!node) return;
    node.innerHTML = '<p class="banner banner-critical">Could not load <code>' + esc(name) +
      '</code>. This section is unavailable; treat its coverage as insufficient rather than ' +
      'as nothing to report. (' + esc(error && error.message) + ')</p>';
  }

  /* ---------------- sections ---------------- */

  function renderBuild(status) {
    el('meta-cutoff').textContent = status.data_cutoff_at || 'unknown';
    el('meta-methodology').textContent = 'v' + status.methodology_version;
    el('meta-coverage').textContent = words(status.live_coverage);
    el('meta-paid').textContent = status.paid_source_dependency === 0 ? '0 (free-only)' : 'review required';
    el('chip-cutoff').textContent = 'Cutoff: ' + (status.data_cutoff_at || 'unknown');
  }

  function cardHtml(card) {
    return '<div class="card"><div class="label">' + esc(card[0]) + '</div>' +
      '<div class="value">' + esc(card[1]) + '</div>' +
      '<div class="note">' + esc(card[2]) + '</div></div>';
  }

  function renderSituation(data) {
    el('situation-cards').innerHTML = [
      ['Overall direction', words(data.overall_direction), 'Transparent roll-up of the lane directions, not a composite score.'],
      ['Evidence coverage', words(data.evidence_coverage), data.coverage_message],
      ['Qualified observations', String(data.qualified_observation_count), 'Live-retrieved or human-reviewed records. Fixtures are excluded.'],
      ['Qualified events', String(data.qualified_event_count), 'Events with retrieved or human-reviewed evidence.'],
      ['Lanes needing attention', String(data.lanes_requiring_attention.length), 'Out of the published lane set.'],
      ['Active verified events', String(data.active_verified_events.length), 'Confirmed still active at the data cutoff.']
    ].map(cardHtml).join('');

    /* R-3 / AC-2: the demonstration count never sits in the same grid as the
       current cards above. It gets its own card, in the demonstration
       region, with its own item-level marker (AC-4). */
    el('situation-demo-cards').innerHTML =
      '<div class="card" data-demo-label="' + attr(DEMO_LABEL.technical_demo) + '">' +
      '<div class="label">Demo lanes at attention ' + demoTag('technical_demo') + '</div>' +
      '<div class="value">' + esc(String(data.demo_summary.lanes_requiring_attention)) + '</div>' +
      '<div class="note">Technical demonstration only — synthetic fixtures.</div></div>';

    var attentionBody = el('attention-table').querySelector('tbody');
    attentionBody.innerHTML = data.lanes_requiring_attention.length
      ? data.lanes_requiring_attention.map(function (lane) {
          return '<tr><th scope="row">' + esc(lane.name) + '<br><small>' + esc(lane.lane_id) + '</small></th>' +
            '<td>' + pill(lane.attention_level, ATTENTION_PILL) + '</td>' +
            '<td>' + pill(lane.overall_direction, DIRECTION_PILL) + '</td>' +
            '<td>' + esc(words(lane.resolution)) + '</td></tr>';
        }).join('')
      : '<tr><td colspan="4">No lane is above routine attention. With no qualified ' +
        'evidence, no lane can be raised — which is a coverage gap, not an all-clear.</td></tr>';

    el('situation-cost-current').textContent =
      'No qualified cost observation exists, so no current cost pressure reading is ' +
      'published. The table below is a technical demonstration built from synthetic ' +
      'fixtures.';

    el('situation-cost-current-series').innerHTML = data.current_cost_pressure.length
      ? '<div class="table-wrap"><table>' +
        '<caption>Current cost-context readings, from qualified records only.</caption>' +
        '<thead><tr><th scope="col">Series</th><th scope="col" class="num">Latest value</th>' +
        '<th scope="col">Period</th><th scope="col" class="num">Month over month</th>' +
        '<th scope="col">Freshness</th></tr></thead><tbody>' +
        data.current_cost_pressure.map(function (item) {
          return '<tr><th scope="row">' + esc(item.series_id) + '<br><small>' +
            esc(item.source_id || '') + ' · ' + esc(words(item.evidence_origin)) + '</small></th>' +
            '<td class="num">' + num(item.current_value, 2) + ' <small>' + esc(item.unit || '') + '</small></td>' +
            '<td>' + esc(item.current_period || 'none') + '</td>' +
            '<td class="num">' + pct(item.month_over_month_pct) + '</td>' +
            '<td>' + freshnessCell(item.freshness) + '</td></tr>';
        }).join('') + '</tbody></table></div>'
      : '';

    var costBody = el('situation-cost-table').querySelector('tbody');
    costBody.innerHTML = data.cost_pressure.map(function (item) {
      return '<tr><th scope="row">' + esc(item.series_id) + '<br><small>' + esc(item.source_id || '') +
        (item.intended_source_id ? ' — stands in for ' + esc(item.intended_source_id) : '') +
        ' · ' + esc(words(item.evidence_origin)) + '</small></th>' +
        '<td class="num">' + num(item.current_value, 2) + ' <small>' + esc(item.unit || '') + '</small></td>' +
        '<td>' + esc(item.current_period || 'none') + '</td>' +
        '<td class="num">' + pct(item.month_over_month_pct) + '</td>' +
        '<td>' + freshnessCell(item.freshness) + '</td></tr>';
    }).join('') || '<tr><td colspan="5">No cost series available.</td></tr>';

    el('situation-changes').innerHTML = data.key_changes.map(function (item) {
      return '<li>' + esc(item) + '</li>';
    }).join('');
    el('situation-gaps').innerHTML = data.major_data_gaps.map(function (item) {
      return '<li>' + esc(item) + '</li>';
    }).join('');
  }

  function domainTable(assessment) {
    var rows = ((assessment && assessment.domain_assessments) || []).map(function (item) {
      return '<tr><th scope="row">' + esc(words(item.domain)) + '</th>' +
        '<td>' + pill(item.direction, DIRECTION_PILL) + '</td>' +
        '<td>' + esc(item.threshold_rule_id || 'no threshold rule (event or coverage derived)') + '</td>' +
        '<td>' + esc(item.data_period || 'none') + '</td>' +
        '<td>' + freshnessCell(item.freshness) + '</td></tr>';
    }).join('');
    return '<div class="table-wrap"><table>' +
      '<caption>Domain-by-domain assessment. Each domain is independently sourced and freshness-stamped; none is inferred from another.</caption>' +
      '<thead><tr><th scope="col">Domain</th><th scope="col">Direction</th>' +
      '<th scope="col">Threshold rule</th><th scope="col">Data period</th><th scope="col">Freshness</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table></div>';
  }

  /* ---------------- ocean: lanes as an expandable-row table ---------------- */

  function toggleRow(btn) {
    var expanded = btn.getAttribute('aria-expanded') === 'true';
    var detail = el(btn.getAttribute('aria-controls'));
    btn.setAttribute('aria-expanded', String(!expanded));
    if (detail) detail.hidden = expanded;
    var glyph = btn.querySelector('[aria-hidden]');
    if (glyph) glyph.textContent = expanded ? '+' : '−';
  }

  function findExpandButtonFor(id) {
    var btns = document.querySelectorAll('.row-expand-btn');
    for (var i = 0; i < btns.length; i += 1) {
      if (btns[i].getAttribute('aria-controls') === id) return btns[i];
    }
    return null;
  }

  function expandRowBtn(detailId, label) {
    return '<button type="button" class="row-expand-btn" aria-expanded="false" aria-controls="' +
      attr(detailId) + '"><span class="visually-hidden">Expand ' + esc(label) + '</span>' +
      '<span aria-hidden="true">+</span></button>';
  }

  /* R-3 (AC-41): the current lane row carries no demonstration value of any
     kind — no pill, no attention level, no direction. It only points at the
     relocated demonstration block, which lives in the demonstration region
     and is rendered by laneDemoBlock() below. */
  function laneCrossReference(lane) {
    if (!lane.demo_assessment) return '';
    return '<p class="demo-cross-ref">A technical-demonstration assessment exists for this lane in the ' +
      'demonstration region below. It describes no real-world condition and carries no current value. ' +
      '<a href="#lane-demo-' + attr(lane.lane_id) + '">See the demonstration assessment</a>.</p>';
  }

  function laneRow(lane) {
    var assessment = lane.assessment;
    var detailId = 'lane-detail-' + lane.lane_id;

    var row = '<tr>' +
      '<td>' + expandRowBtn(detailId, lane.name) + '</td>' +
      '<th scope="row">' + esc(lane.name) + '<br><small>' + esc(lane.lane_id) + '</small></th>' +
      '<td>' + (assessment ? pill(assessment.attention_level, ATTENTION_PILL) : pill('insufficient_evidence', ATTENTION_PILL)) + '</td>' +
      '<td>' + (assessment ? pill(assessment.overall_direction, DIRECTION_PILL) : '') + '</td>' +
      '<td>' + esc(words(lane.resolution)) + '</td>' +
      '<td>' + esc(lane.mode) + '</td>' +
      '<td>' + (lane.chokepoint_ids.length ? esc(lane.chokepoint_ids.join(', ')) : 'none registered') + '</td>' +
      '</tr>';

    var selectionRows = lane.selection_evidence.map(function (item) {
      return '<tr><th scope="row">' + esc(words(item.criterion)) + '</th><td>' + esc(item.statement) + '</td>' +
        '<td>' + pill(item.evidence_class, {}) + '</td>' +
        '<td>' + esc(item.source_reference || 'none') + '</td></tr>';
    }).join('');

    var detail = '<tr class="detail-row" id="' + attr(detailId) + '" hidden><td colspan="7">' +
      '<p class="meta">' + esc(lane.origin) + ' → ' + esc(lane.destination) +
      ' · reviewed ' + esc(lane.review_date) + ' · ' + esc(lane.status) + '</p>' +
      '<p class="pill pill-note">current</p>' +
      detailsBlock('Current domain assessments (9)', domainTable(assessment)) +
      (assessment && assessment.data_gaps
        ? detailsBlock('Current data gaps (' + assessment.data_gaps.length + ')', list(assessment.data_gaps))
        : '') +
      laneCrossReference(lane) +
      detailsBlock('Selection evidence (' + lane.selection_evidence.length + ')',
        '<div class="table-wrap"><table><caption>Why this lane was selected, and on what basis.</caption>' +
        '<thead><tr><th scope="col">Criterion</th><th scope="col">Statement</th>' +
        '<th scope="col">Evidence class</th><th scope="col">Reference</th></tr></thead><tbody>' +
        selectionRows + '</tbody></table></div>' +
        '<p class="prose"><strong>Data period used:</strong> ' + esc(lane.data_period_used || 'none — no dated quantitative evidence was retrieved') + '</p>') +
      detailsBlock('Known limitations (' + lane.known_limitations.length + ')', list(lane.known_limitations)) +
      '</td></tr>';

    return row + detail;
  }

  /* Relocated demonstration lane assessment (was: the in-card demo panel).
     Keeps the `demo-panel` class and its own data-demo-label so the existing
     per-item-marking test keeps binding to live markup, per AC-41. */
  function laneDemoBlock(lane) {
    var demo = lane.demo_assessment;
    if (!demo) return '';
    return '<div class="lane-card demo-panel" id="lane-demo-' + attr(lane.lane_id) + '" ' +
      'data-demo-label="' + attr(DEMO_LABEL[demo.dataset] || 'Technical demonstration') + '">' +
      '<div class="badges">' + demoTag(demo.dataset) + pill(demo.attention_level, ATTENTION_PILL) +
      pill(demo.overall_direction, DIRECTION_PILL) + '</div>' +
      '<h4>' + esc(lane.name) + ' <small>' + esc(lane.lane_id) + '</small></h4>' +
      '<p class="meta">Derived from synthetic fixtures to exercise the threshold rules. ' +
      'This attention level describes no real-world condition and must not be quoted as one.</p>' +
      detailsBlock('Demonstration domain assessments (9)', domainTable(demo)) +
      '</div>';
  }

  function renderOcean(data) {
    el('port-note').textContent = data.port_interpretation_note;
    el('ocean-demo-label').textContent = data.demo_label;
    el('current-notice-statement').textContent = data.current_notice_statement;

    el('current-port-series').innerHTML = data.current_port_series.length
      ? data.current_port_series.map(function (series) {
          return seriesBlock(series, series.series_id, [
            'Metric: ' + words(series.metric || ''),
            'Interpretation: volume only'
          ]);
        }).join('')
      : '<p class="empty-state">No qualified port or maritime observation exists, so no ' +
        'current reading is published. This is a coverage gap, not a finding that activity ' +
        'is normal.</p>';

    el('current-notices').innerHTML = data.current_operational_notices.length
      ? data.current_operational_notices.map(function (notice) {
          return '<div class="event"><div class="badges">' +
            '<span class="pill pill-note">current</span>' +
            '<span class="pill pill-muted">' + esc(words(notice.evidence_origin)) + '</span>' +
            '<span class="pill pill-muted">' + esc(words(notice.retrieval_status)) + '</span>' +
            '</div><h4>' + esc(notice.source_name) + '</h4>' +
            (notice.underlying_publisher
              ? '<p class="meta">Underlying publisher: ' + esc(notice.underlying_publisher) + '</p>'
              : '') +
            '<p class="prose">' + esc(notice.claim) + '</p>' +
            '<p class="meta"><small>Published ' + esc(notice.publication_date || 'unknown') +
            externalLink(notice.source_url, 'source') +
            '</small></p>' +
            detailsBlock('Known limitations', list(notice.known_limitations)) +
            '</div>';
        }).join('')
      : '';

    el('current-capacity-table').querySelector('tbody').innerHTML =
      data.current_capacity_and_service_evidence.length
        ? data.current_capacity_and_service_evidence.map(function (item) {
            return '<tr><th scope="row">' + esc(item.title) + '<br><small>' + esc(item.event_id) +
              '</small></th><td>' + esc(item.area) + '</td>' +
              '<td>' + pill(item.status, STATUS_PILL) + '</td>' +
              '<td>' + esc(item.severity) + '</td>' +
              '<td>' + esc(item.evidence_strength) + '</td>' +
              '<td>' + esc(item.confidence) + '</td></tr>';
          }).join('')
        : '<tr><td colspan="6">No qualified capacity or service impact is recorded against a ' +
          'currently active event. This is a coverage gap, not an all-clear.</td></tr>';

    el('lane-cards').innerHTML = data.lanes.map(laneRow).join('');

    var laneByChokepoint = {};
    data.lanes.forEach(function (lane) {
      lane.chokepoint_ids.forEach(function (id) {
        (laneByChokepoint[id] = laneByChokepoint[id] || []).push(lane.lane_id);
      });
    });
    var noticeStatus = {};
    data.lanes.forEach(function (lane) {
      ((lane.assessment && lane.assessment.chokepoint_exposure) || []).forEach(function (entry) {
        if (entry.status !== 'no_notice') noticeStatus[entry.chokepoint_id] = entry.status;
      });
    });

    el('chokepoint-table').querySelector('tbody').innerHTML = data.chokepoints.map(function (cp) {
      var status = noticeStatus[cp.chokepoint_id] || 'no_notice';
      return '<tr><th scope="row">' + esc(cp.name) + '<br><small>' + esc(cp.chokepoint_id) + '</small></th>' +
        '<td>' + esc(words(cp.chokepoint_type)) + '</td>' +
        '<td>' + esc(cp.modes.join(', ')) + '</td>' +
        '<td>' + esc(cp.operating_authority || 'none registered') + '</td>' +
        '<td>' + esc((laneByChokepoint[cp.chokepoint_id] || []).join(', ') || 'no lane exposed') + '</td>' +
        '<td>' + pill(status, { official_notice_active: 'pill-critical', no_notice: 'pill-muted' }) + '</td></tr>';
    }).join('');

    el('port-series').innerHTML = data.demo_port_series.map(function (series) {
      return seriesBlock(series, series.series_id, [
        'Metric: ' + words(series.metric),
        'Interpretation: ' + words(series.operational_interpretation),
        'Resolution: ' + words(series.resolution),
        series.node_id || 'country level'
      ]);
    }).join('') || '<p class="empty-state">No port series available.</p>';

    el('lane-demo-cards').innerHTML = data.lanes.map(laneDemoBlock).join('') ||
      '<p class="empty-state">No demonstration lane assessment was generated.</p>';

    el('notices').innerHTML = data.demo_operational_notices.length
      ? data.demo_operational_notices.map(function (notice) {
          return '<div class="event is-demo" data-demo-label="' +
            attr(DEMO_LABEL[notice.dataset] || '') + '"><div class="badges">' +
            demoTag(notice.dataset) +
            (notice.assessment_cutoff
              ? '<span class="pill pill-muted">assessed at cutoff ' + esc(notice.assessment_cutoff.slice(0, 10)) + '</span>'
              : '') +
            (notice.case_id ? '<span class="pill pill-muted">' + esc(notice.case_id) + '</span>' : '') +
            '<span class="pill pill-note">official notice</span>' +
            '<span class="pill pill-muted">' + esc(words(notice.retrieval_status)) + '</span>' +
            '<span class="pill pill-muted">' + esc(notice.source_class) + '</span>' +
            '<span class="pill pill-muted">licence: ' + esc(words(notice.licence_status)) + '</span></div>' +
            '<h4>' + esc(notice.source_name) + '</h4>' +
            '<p class="prose">' + esc(notice.claim) + '</p>' +
            '<p class="meta"><small>Published ' + esc(notice.publication_date || 'unknown') +
            ' · recorded ' + esc(notice.retrieved_at) +
            externalLink(notice.source_url, 'source') +
            '</small></p>' +
            detailsBlock('Known limitations', list(notice.known_limitations)) +
            '</div>';
        }).join('')
      : '<p class="empty-state">No official operational notice is recorded. No notice channel is monitored live, ' +
        'so this is an absence of records rather than evidence that no notice was published.</p>';

    el('capacity-table').querySelector('tbody').innerHTML = data.demo_capacity_and_service_evidence.length
      ? data.demo_capacity_and_service_evidence.map(function (item) {
          return '<tr><th scope="row">' + esc(item.title) + '<br><small>' + esc(item.event_id) +
            ' · cutoff ' + esc((item.assessment_cutoff || '').slice(0, 10)) + '</small></th>' +
            '<td>' + esc(item.area) + '</td>' +
            '<td>' + pill(item.status, STATUS_PILL) + '</td>' +
            '<td>' + esc(item.severity) + '</td>' +
            '<td>' + esc(item.evidence_strength) + '</td>' +
            '<td>' + esc(item.confidence) + '</td></tr>';
        }).join('')
      : '<tr><td colspan="6">No capacity or service impact is recorded.</td></tr>';
  }

  function renderTrade(data) {
    el('trade-current').textContent = data.current_statement;
    el('trade-demo-label').textContent = data.demo_label;
    el('current-trade-lanes').innerHTML = data.current_lane_flows.length
      ? data.current_lane_flows.map(function (lane) {
          return '<div class="series"><h4>' + esc(lane.name) + '</h4>' +
            lane.flows.map(function (flow) {
              return seriesBlock(flow, lane.name + ' — ' + flow.flow_direction, [
                'Flow: ' + words(flow.flow_direction)
              ]);
            }).join('') + '</div>';
        }).join('')
      : '<p class="empty-state">No qualified trade-value observation exists for any lane, so no ' +
        'current reading is published. This is a coverage gap, not evidence that trade stopped.</p>';
    el('trade-note').innerHTML = esc(data.lane_selection_note) + ' ' + esc(data.revision_note);
    el('trade-lanes').innerHTML = data.lane_flows.map(function (lane) {
      var body = lane.flows.map(function (flow) {
        return seriesBlock(flow, lane.name + ' — ' + flow.flow_direction, [
          'Partner: ' + flow.partner_label,
          'Partner scope: ' + words(flow.partner_scope),
          'Measure: ' + words(flow.measure)
        ]);
      }).join('') || '<p class="empty-state">No trade series recorded for this lane.</p>';
      return '<div class="series"><h4>' + esc(lane.name) + '</h4>' +
        '<p class="series-meta">' + esc(lane.partner_scope_note) + '</p>' + body + '</div>';
    }).join('');
  }

  function renderCost(data) {
    el('cost-current').textContent = data.current_statement;
    el('cost-demo-label').textContent = data.demo_label;
    el('current-cost-series').innerHTML = data.current_cost_series.length
      ? data.current_cost_series.map(function (series) {
          return seriesBlock(series, series.series_id, ['Current cost-context reading']);
        }).join('')
      : '<p class="empty-state">No qualified cost-context reading exists, so no current value is ' +
        'published. This is a coverage gap, not evidence that costs are stable.</p>';
    el('cost-limits-banner').innerHTML =
      '<strong>These are benchmarks, not quotations.</strong>' +
      esc(data.benchmark_limitations[1]);
    el('cost-series').innerHTML = data.cost_series.map(function (series) {
      return seriesBlock(series, series.series_id, [
        'Cost family: ' + words(series.cost_family),
        'Benchmark class: ' + words(series.benchmark_class),
        words(series.quotation_claim),
        'Route scope: ' + (series.route_scope || 'not route specific'),
        'Thailand applicability: ' + words(series.applies_to_thailand)
      ]);
    }).join('');
    el('fx-series').innerHTML = seriesBlock(data.fx, 'USD/THB reference rate', [
      'Cost-context indicator only',
      'A rate change does not establish a change in any cost actually paid'
    ]);
    el('cost-limitations').innerHTML = data.benchmark_limitations.map(function (item) {
      return '<li>' + esc(item) + '</li>';
    }).join('');
    el('surcharge-note').textContent = data.surcharge_note;
  }

  function chainList(chain) {
    var links = [
      ['External driver', chain.external_driver],
      ['Operational change', chain.operational_change],
      ['Logistics mechanism', chain.logistics_mechanism],
      ['Observable indicator', chain.observable_indicator],
      ['Outcome', chain.outcome]
    ];
    return '<ul class="chain">' + links.map(function (link) {
      if (!link[1]) {
        return '<li class="absent"><strong>' + esc(link[0]) + ':</strong> not established</li>';
      }
      return '<li><strong>' + esc(link[0]) + ':</strong> ' + esc(link[1]) + '</li>';
    }).join('') + '</ul>' +
      '<p class="prose"><strong>Chain completeness:</strong> ' +
      pill(chain.completeness, { complete: 'pill-ok', incomplete: 'pill-warning', not_applicable: 'pill-muted' }) +
      (chain.missing_links && chain.missing_links.length
        ? ' <small>Missing: ' + esc(chain.missing_links.join(', ')) + '</small>' : '') + '</p>';
  }

  function eventCard(event) {
    var impactRows = event.impact_assessments.map(function (impact) {
      return '<tr><th scope="row">' + esc(words(impact.area)) + '</th>' +
        '<td>' + pill(impact.status, STATUS_PILL) + '</td>' +
        '<td>' + esc(impact.severity) + '</td>' +
        '<td>' + esc(impact.relevance) + '</td>' +
        '<td>' + esc(impact.evidence_strength) + '</td>' +
        '<td>' + esc(impact.confidence) + '</td>' +
        '<td>' + esc(words(impact.time_horizon)) + '</td>' +
        '<td>' + (impact.transmission_mechanism.length ? esc(impact.transmission_mechanism.join(' ')) : '<span class="missing">none stated</span>') + '</td></tr>';
    }).join('');

    var evidenceRows = event.evidence.map(function (item) {
      return '<tr><th scope="row">' + esc(item.source_name) + '<br><small>' + esc(item.evidence_id) + '</small></th>' +
        '<td>' + pill(item.claim_type, {}) + '</td>' +
        '<td>' + pill(item.evidence_role, { confirming: 'pill-ok', contextual: 'pill-note', discovery_only: 'pill-muted' }) + '</td>' +
        '<td>' + esc(item.strength) +
        '<br><small>' + esc(words(item.strength_basis)) + '</small></td>' +
        '<td>' + esc(words(item.evidence_origin)) +
        (item.intended_source_id ? '<br><small>stands in for ' + esc(item.intended_source_id) + '</small>' : '') +
        '</td>' +
        '<td>' + esc(words(item.retrieval_status)) + '</td>' +
        '<td>' + esc(item.publication_date || 'unknown') + '</td>' +
        '<td>' + (item.retrieved_at ? esc(item.retrieved_at) : '<span class="missing">never retrieved</span>') + '</td>' +
        '<td>' + esc(item.claim) + externalLink(item.source_url, 'source') +
        '</td></tr>';
    }).join('');

    var demoLabel = DEMO_LABEL[event.dataset] || '';

    return '<article class="event' + (demoLabel ? ' is-demo' : '') + '"' +
      (demoLabel ? ' data-demo-label="' + attr(demoLabel) + '"' : '') + '>' +
      '<div class="badges">' +
      demoTag(event.dataset) +
      (event.assessment_cutoff
        ? '<span class="pill pill-demo">assessed at cutoff ' + esc(String(event.assessment_cutoff).slice(0, 10)) + '</span>'
        : '') +
      (event.case_id ? '<span class="pill pill-muted">' + esc(event.case_id) + '</span>' : '') +
      pill(event.event_class, { direct_operational_event: 'pill-critical', external_driver: 'pill-warning', discovery_lead: 'pill-muted' }) +
      pill(event.lifecycle_status, {}) +
      '<span class="pill pill-muted">' + esc(words(event.event_type)) + '</span>' +
      '<span class="pill pill-note">Thailand relevance: ' + esc(words(event.thailand_relevance)) + '</span>' +
      '<span class="pill pill-muted">event severity: ' + esc(words(event.event_severity)) + '</span>' +
      (event.human_review.required ? '<span class="pill pill-critical">human review ' + esc(event.human_review.status) + '</span>' : '') +
      '</div>' +
      '<h4>' + esc(event.title) + '</h4>' +
      '<p class="meta"><small>' + esc(event.event_id) +
      ' · event date ' + esc(event.event_date || 'unknown') +
      ' · published ' + esc(event.publication_date || 'unknown') +
      ' · retrieved ' + esc(event.retrieval_date) +
      ' · last reviewed ' + esc(event.last_reviewed_at) +
      ' · ' + (event.active_as_of
        ? 'confirmed active as of ' + esc(String(event.active_as_of).slice(0, 10)) +
          ' (' + esc(words(event.active_basis)) + ')'
        : 'no confirmation that this event is still active') +
      '</small></p>' +
      chainList(event.transmission_chain) +
      (event.thailand_relevance_basis.length
        ? '<p class="prose"><strong>Thailand relevance basis:</strong></p>' + list(event.thailand_relevance_basis)
        : '<p class="prose"><strong>Thailand relevance:</strong> none established. The platform has found no basis to assess a Thailand effect; this is not a finding that there is none.</p>') +
      (event.closure_basis ? '<p class="prose"><strong>Closure basis:</strong> ' + esc(event.closure_basis) + '</p>' : '') +
      detailsBlock('Lane relevance (' + event.lane_relevance.length + ')',
        event.lane_relevance.length
          ? '<div class="table-wrap"><table><caption>Which lanes this event is relevant to, and why.</caption>' +
            '<thead><tr><th scope="col">Lane</th><th scope="col">Relevance</th><th scope="col">Basis</th></tr></thead><tbody>' +
            event.lane_relevance.map(function (entry) {
              return '<tr><th scope="row">' + esc(entry.lane_id) + '</th><td>' + esc(entry.relevance) + '</td><td>' + esc(entry.basis) + '</td></tr>';
            }).join('') + '</tbody></table></div>'
          : '<p class="empty-state">No lane relevance established.</p>') +
      detailsBlock('Nine-area impact assessment',
        '<div class="table-wrap"><table><caption>Impact by area. Event severity, impact severity, evidence strength and confidence are recorded separately.</caption>' +
        '<thead><tr><th scope="col">Area</th><th scope="col">Status</th>' +
        '<th scope="col">Severity</th><th scope="col">Relevance</th><th scope="col">Evidence</th>' +
        '<th scope="col">Confidence</th><th scope="col">Horizon</th><th scope="col">Transmission mechanism</th></tr></thead>' +
        '<tbody>' + impactRows + '</tbody></table></div>' +
        '<p class="prose"><small>Event severity, impact severity, evidence strength and confidence are ' +
        'recorded separately and none is inferred from another. ' +
        (event.negative_operational_evidence
          ? 'This event carries explicit negative operational evidence, which is what permits a no-material-impact finding.'
          : 'This event carries no negative operational evidence, so no area may report no material impact.') +
        '</small></p>') +
      detailsBlock('Evidence (' + event.evidence.length + ')',
        '<div class="table-wrap"><table><caption>Every evidence record behind this event, with its retrieval and publication status.</caption>' +
        '<thead><tr><th scope="col">Source</th><th scope="col">Claim type</th>' +
        '<th scope="col">Role</th><th scope="col">Strength</th><th scope="col">Origin</th>' +
        '<th scope="col">Retrieval</th><th scope="col">Published</th>' +
        '<th scope="col">Retrieved</th><th scope="col">Claim</th></tr></thead><tbody>' + evidenceRows + '</tbody></table></div>' +
        '<p class="prose"><small>Strength recorded as <em>expected at cutoff</em> is the strength a ' +
        'qualified source would have carried had it been retrieved. It has not been verified ' +
        'against any retrieved document.</small></p>') +
      detailsBlock('Conflicting evidence (' + event.conflicting_evidence.length + ')',
        event.conflicting_evidence.length
          ? list(event.conflicting_evidence.map(function (c) { return c.description + ' — ' + words(c.resolution_status); }))
          : '<p class="empty-state">No conflicting evidence is recorded for this event.</p>') +
      detailsBlock('Known limitations (' + event.known_limitations.length + ')', list(event.known_limitations)) +
      '</article>';
  }

  function renderEvents(data) {
    el('events-note').textContent = data.lifecycle_note;
    el('events-current-statement').textContent = data.current_statement;
    el('events-demo-label').textContent = data.demo_label;
    [
      ['events-current-operational', data.current_direct_operational_events,
        'No current direct operational event is recorded. Every event held is a historical ' +
        'validation fixture. An empty list here is a coverage gap, not an all-clear.'],
      ['events-current-drivers', data.current_external_drivers,
        'No current external driver is recorded. An empty list here is a coverage gap, not a ' +
        'finding that no driver exists.'],
      ['events-operational', data.demo_direct_operational_events, 'No direct operational event is recorded.'],
      ['events-admitted', data.demo_admitted_external_drivers, 'No external driver currently has a complete transmission chain.'],
      ['events-contextual', data.demo_contextual_external_drivers, 'No contextual external driver is recorded.'],
      ['events-leads', data.demo_discovery_leads, 'No discovery lead is recorded.']
    ].forEach(function (entry) {
      el(entry[0]).innerHTML = entry[1].length
        ? entry[1].map(eventCard).join('')
        : '<p class="empty-state">' + esc(entry[2]) + '</p>';
    });
  }

  function scenarioCase(name, item) {
    if (!item) return '';
    return '<div class="series"><h4>' + esc(name) + '</h4>' +
      '<p class="series-meta">Horizon: ' + esc(words(item.time_horizon)) +
      ' · Confidence: ' + esc(item.confidence) + '</p>' +
      '<p class="prose">' + esc(item.narrative) + '</p>' +
      (item.point_forecast_disclaimer ? '<p class="prose"><small>' + esc(item.point_forecast_disclaimer) + '</small></p>' : '') +
      '<div class="table-wrap"><table><caption>Trigger conditions: what would have to be observed, and where.</caption>' +
      '<thead><tr><th scope="col">Condition</th><th scope="col">Observable via</th></tr></thead><tbody>' +
      item.trigger_conditions.map(function (trigger) {
        return '<tr><td>' + esc(trigger.condition) + '</td><td>' + esc(trigger.observable_via) + '</td></tr>';
      }).join('') + '</tbody></table></div>' +
      detailsBlock('Data gaps (' + item.data_gaps.length + ')', list(item.data_gaps, 'None recorded.')) +
      '</div>';
  }

  function renderOutlook(data) {
    var status = el('ai-status');
    status.className = 'banner ' + (data.review_status === 'approved' ? 'banner-note' : 'banner-critical');
    status.textContent = data.status_message;
    el('ai-boundary').textContent = data.boundary_note;
    el('ai-package-note').textContent = data.package_boundary_note;

    el('withheld-assessments').innerHTML = data.withheld_assessments.length
      ? '<p class="banner banner-critical"><strong>Withheld from publication.</strong>' +
        esc(data.publication_gate_note) + '</p>' +
        data.withheld_assessments.map(function (item) {
          return '<div class="series"><h4>' + esc(item.package_id) + '</h4>' +
            '<p class="meta">Bound to a ' + esc(words(item.input_dataset)) + ' package.</p>' +
            list(item.reasons) + '</div>';
        }).join('')
      : '';

    el('approved-assessments').innerHTML = data.approved_assessments.length
      ? data.approved_assessments.map(function (item) {
          return '<div class="series"><h4>' + esc(item.package_id) + '</h4>' +
            '<p class="series-meta">Approved ' + esc(item.approved_at) + ' by ' + esc(item.reviewer_record) + '</p>' +
            '<p class="prose">' + esc(item.assessment.current_situation) + '</p></div>';
        }).join('')
      : '<p class="empty-state">No AI assessment has been approved for publication. This is a ' +
        'coverage gap, not evidence that no assessment was produced.</p>';

    el('deterministic-note').textContent = data.deterministic_note;
    el('outlook-demo-label').textContent = data.demo_label;
    el('current-outlooks').innerHTML = (data.current_outlooks || []).map(outlookBlock).join('') ||
      '<p class="empty-state">No current lane outlook is published.</p>';
    el('outlooks').innerHTML = (data.demo_outlooks || []).map(outlookBlock).join('') ||
      '<p class="empty-state">No demonstration outlook was generated.</p>';
  }

  function outlookBlock(entry) {
    var scenarios = entry.scenarios;
    var demoLabel = DEMO_LABEL[entry.dataset] || '';
    return '<div class="series' + (demoLabel ? ' is-demo' : '') + '"' +
      (demoLabel ? ' data-demo-label="' + attr(demoLabel) + '"' : '') + '>' +
      '<div class="badges">' + pill(entry.attention_level, ATTENTION_PILL) + demoTag(entry.dataset) + '</div>' +
      '<h4>' + esc(entry.lane_name || entry.lane_id) + '</h4>' +
      (scenarios
        ? scenarioCase('Base case', scenarios.base_case) +
          scenarioCase('Deterioration case', scenarios.deterioration_case) +
          scenarioCase('Improvement case', scenarios.improvement_case)
        : '<p class="empty-state">No outlook generated for this lane.</p>') +
      detailsBlock('Conditional preparedness options (' + entry.preparedness_options.length + ')',
        entry.preparedness_options.length
          ? entry.preparedness_options.map(function (option) {
              return '<div class="series"><h4>' + esc(words(option.option_type)) + '</h4>' +
                '<p class="prose">' + esc(option.description) + '</p>' +
                '<p class="prose"><strong>Applies to:</strong> ' + esc(option.applicable_to) + '</p>' +
                '<p class="prose"><strong>Trigger:</strong> ' + esc(option.trigger_condition) + '</p>' +
                '<p class="prose"><strong>Exit:</strong> ' + esc(option.exit_condition) + '</p>' +
                detailsBlock('Trade-offs and limitations',
                  list((option.tradeoffs || []).concat(option.limitations || []))) +
                '</div>';
            }).join('')
          : '<p class="empty-state">No preparedness option applies.</p>') +
      '</div>';
  }

  /* ---------------- sources: expandable-row table + payload manifest ---------------- */

  function sourceRow(source) {
    var health = source.health || {};
    var detailId = 'source-detail-' + source.source_id;
    var blockerCount = (source.blockers || []).length;

    var row = '<tr>' +
      '<td>' + expandRowBtn(detailId, source.name) + '</td>' +
      '<th scope="row">' + esc(source.name) + '<br><small>' + esc(source.source_id) + '</small></th>' +
      '<td>' + esc(source.owner) + '</td>' +
      '<td>' + esc(words(source.source_class)) + '</td>' +
      '<td>' + esc(words(source.licence_status)) + '</td>' +
      '<td>' + (source.enabled ? 'yes' : 'no') + '</td>' +
      '<td>' + pill(health.status || 'unknown', FRESHNESS_PILL) + '</td>' +
      '<td>' + (blockerCount ? blockerCount + ' recorded' : 'none recorded') + '</td>' +
      '</tr>';

    var fieldRows = [
      ['Owner', source.owner],
      ['Class', words(source.source_class)],
      ['Landing page', source.landing_url],
      ['Endpoint', source.endpoint || 'none recorded'],
      ['Access method', words(source.access_method) + ' · ' + source.format],
      ['Machine readable', words(source.machine_readable_status)],
      ['Licence status', words(source.licence_status)],
      ['Terms', source.terms_url || 'not recorded'],
      ['Access cost', words(source.access_cost || 'not recorded')],
      ['Reuse status', words(source.reuse_status || 'not recorded')],
      ['Redistribution', words(source.redistribution_status || 'not recorded')],
      ['Publication cadence', source.publication_cadence || 'not recorded'],
      ['Observed freshness', source.observed_freshness || 'never observed'],
      ['Data period', source.data_period || 'not established'],
      ['Logistics role', (source.logistics_role || []).map(words).join(', ') || 'not recorded'],
      ['Prototype eligibility', words(source.prototype_eligibility || 'unknown')],
      ['Live validation', words(source.live_validation_status || 'not recorded')],
      ['Enabled', source.enabled ? 'yes' : 'no'],
      ['Required for publication', source.required_for_publication ? 'yes' : 'no'],
      ['Health status', words(health.status || 'unknown')]
    ].map(function (pair) {
      return '<tr><th scope="row">' + esc(pair[0]) + '</th><td>' + esc(pair[1]) + '</td></tr>';
    }).join('');

    var detail = '<tr class="detail-row" id="' + attr(detailId) + '" hidden><td colspan="8">' +
      '<div class="table-wrap"><table><caption>Full registry record for ' + esc(source.name) + '.</caption>' +
      '<thead><tr><th scope="col">Field</th><th scope="col">Value</th></tr></thead>' +
      '<tbody>' + fieldRows + '</tbody></table></div>' +
      detailsBlock('Enablement blockers (' + blockerCount + ')', list(source.blockers, 'No blocker recorded.')) +
      detailsBlock('Known limitations (' + source.known_limitations.length + ')', list(source.known_limitations)) +
      '</td></tr>';

    return row + detail;
  }

  /* Static manifest, not fetched: every file this build publishes under
     data/, whether this page consumes it, and its dataset classification.
     indicators.json and source_status.json are generated for inspection and
     reproducibility but are not read by this page (AC-37/AC-42/AC-43). */
  var PAYLOAD_MANIFEST = [
    ['thailand_situation.json', 'current + technical_demo', true],
    ['ocean.json', 'current + technical_demo + historical_validation', true],
    ['trade.json', 'current + technical_demo', true],
    ['cost.json', 'current + technical_demo', true],
    ['events.json', 'current + technical_demo + historical_validation', true],
    ['ai_outlook.json', 'current + technical_demo', true],
    ['sources.json', 'current', true],
    ['build_status.json', 'current', true],
    ['indicators.json', 'current (generated summary)', false],
    ['source_status.json', 'current (generated summary)', false]
  ];

  function renderPayloadList() {
    el('payload-list').innerHTML = PAYLOAD_MANIFEST.map(function (item) {
      return '<tr><th scope="row"><code>' + esc(item[0]) + '</code></th><td>' + esc(item[1]) + '</td>' +
        '<td>' + (item[2] ? 'yes' : 'no — generated for inspection and reproducibility, not fetched by this page') + '</td></tr>';
    }).join('');
  }

  function renderSources(data) {
    el('sources-cards').innerHTML = [
      ['Registry version', data.registry_version, 'Last reviewed ' + data.last_reviewed_at],
      ['Policy', words(data.policy), 'Paid-source dependency is zero by policy.'],
      ['Sources registered', String(data.sources.length), 'Across every logistics role.'],
      ['Sources enabled', String(data.sources.filter(function (s) { return s.enabled; }).length), 'An enabled source has no unresolved blockers.'],
      ['Overall coverage', words(data.overall_status), data.coverage_message],
      ['Historical validation', words(data.validation_overall), 'Every documented case replayed through the analysis code.']
    ].map(cardHtml).join('');

    el('capability-table').querySelector('tbody').innerHTML = data.capabilities.map(function (item) {
      return '<tr><th scope="row">' + esc(words(item.capability)) + '</th>' +
        '<td>' + pill(item.status, { sufficient: 'pill-ok', limited: 'pill-warning', insufficient: 'pill-critical' }) + '</td>' +
        '<td>' + esc(item.supporting_sources.join(', ')) + '</td>' +
        '<td>' + esc(item.gap_reason || 'none') + '</td></tr>';
    }).join('');

    el('source-list').innerHTML = data.sources.map(sourceRow).join('');

    el('validation-table').querySelector('tbody').innerHTML = Object.keys(data.validation_summary)
      .filter(function (key) { return key.indexOf('_examples') === -1; })
      .sort()
      .map(function (key) {
        var value = data.validation_summary[key];
        return '<tr><th scope="row">' + esc(words(key)) + '</th><td>' +
          esc(Array.isArray(value) ? (value.length ? value.join('; ') : 'none') : String(value)) +
          '</td></tr>';
      }).join('');

    el('methodology-docs').innerHTML = data.methodology.documents.map(function (doc) {
      return '<li><code>' + esc(doc) + '</code></li>';
    }).join('');

    renderPayloadList();
  }

  /* ---------------- coverage chip + banner: one function, two writers ---------------- */

  var COVERAGE_MESSAGES = {
    loading: ['pill-muted', 'banner-critical', 'Live coverage: loading…', 'Payloads are still loading.'],
    load_failed: ['pill-critical', 'banner-critical', 'Live coverage: load failed',
      'One or more dashboard payloads failed to load. Treat coverage as insufficient until the page loads completely.'],
    insufficient: ['pill-critical', 'banner-critical', 'Live coverage: insufficient', null],
    sufficient: ['pill-ok', 'banner-note', 'Live coverage: sufficient', null]
  };

  var coverageState = 'loading';

  /* The single function that writes both the persistent navbar chip and the
     Overview banner (AC-9). Once load_failed, there is no exit transition:
     the chip stays pessimistic for the rest of the page's life. */
  function paintCoverage() {
    var chip = el('chip-coverage');
    var config = COVERAGE_MESSAGES[coverageState];
    chip.className = 'pill ' + config[0];
    chip.textContent = config[2];

    var banner = el('coverage-banner');
    if (!banner) return;
    banner.className = 'banner ' + config[1];
    if (coverageState === 'sufficient' || coverageState === 'insufficient') {
      var situation = payloadData['thailand_situation.json'];
      banner.innerHTML = '<strong>Live coverage: ' + esc(words(situation.evidence_coverage)) + '.</strong> ' +
        esc(situation.live_coverage_statement) + ' <br><small>' + esc(situation.coverage_message) +
        ' Data cutoff ' + esc(situation.data_cutoff_at) + '.</small>';
    } else {
      banner.textContent = config[3];
    }
  }

  function driveCoverage() {
    if (coverageState === 'load_failed') { paintCoverage(); return; }
    var anyFailed = PAYLOAD_FILES.some(function (f) { return loaded[f] && loaded[f].ok === false; });
    if (anyFailed) { coverageState = 'load_failed'; paintCoverage(); return; }
    var allSettled = PAYLOAD_FILES.every(function (f) { return loaded[f]; });
    if (!allSettled) { coverageState = 'loading'; paintCoverage(); return; }
    var situation = payloadData['thailand_situation.json'];
    coverageState = situation.evidence_coverage === 'sufficient' ? 'sufficient' : 'insufficient';
    paintCoverage();
  }

  /* ---------------- router ---------------- */

  var VIEWS = [
    { route: 'overview', id: 'situation', title: 'Overview', label: 'Overview view' },
    { route: 'ocean', id: 'ocean', title: 'Ocean Operations', label: 'Ocean Operations view' },
    { route: 'trade', id: 'trade', title: 'Trade & Flow', label: 'Trade & Flow view' },
    { route: 'cost', id: 'cost', title: 'Cost & Freight', label: 'Cost & Freight view' },
    { route: 'events', id: 'events', title: 'Events', label: 'Events view' },
    { route: 'outlook', id: 'outlook', title: 'Outlook', label: 'Outlook view' },
    { route: 'sources', id: 'sources', title: 'Sources & Methodology', label: 'Sources & Methodology view' }
  ];
  var ROUTE_TO_ID = {};
  var VIEW_BY_ROUTE = {};
  VIEWS.forEach(function (v) { ROUTE_TO_ID[v.route] = v.id; VIEW_BY_ROUTE[v.route] = v; });
  var LEGACY_TO_ROUTE = { situation: 'overview' };

  var currentRoute = null;
  var renderedViews = {};
  /* A sub-anchor whose target didn't exist yet because its view's payload
     hadn't rendered when the hash was first resolved (AC-12 on a fresh page
     load racing the async fetch). Retried once that view actually renders. */
  var pendingSub = null;

  var PAYLOAD_FILES = [
    'thailand_situation.json', 'ocean.json', 'trade.json', 'cost.json',
    'events.json', 'ai_outlook.json', 'sources.json', 'build_status.json'
  ];
  var ROUTE_FOR_FILE = {
    'thailand_situation.json': 'overview',
    'ocean.json': 'ocean',
    'trade.json': 'trade',
    'cost.json': 'cost',
    'events.json': 'events',
    'ai_outlook.json': 'outlook',
    'sources.json': 'sources'
  };
  var RENDER_FN = {
    'thailand_situation.json': renderSituation,
    'ocean.json': renderOcean,
    'trade.json': renderTrade,
    'cost.json': renderCost,
    'events.json': renderEvents,
    'ai_outlook.json': renderOutlook,
    'sources.json': renderSources
  };
  var FALLBACK_CONTAINER = {
    'thailand_situation.json': 'situation-cards',
    'ocean.json': 'port-series',
    'trade.json': 'trade-lanes',
    'cost.json': 'cost-series',
    'events.json': 'events-operational',
    'ai_outlook.json': 'outlooks',
    'sources.json': 'source-list'
  };

  var loaded = {};
  var payloadData = {};

  function fileForRoute(route) {
    var file = null;
    Object.keys(ROUTE_FOR_FILE).forEach(function (f) { if (ROUTE_FOR_FILE[f] === route) file = f; });
    return file;
  }

  /* Renders a view's payload unconditionally, once its data has settled.
     Idempotent: a view is only ever rendered once (AC-27). Used directly by
     print (AC-35, every view must be printable even if never visited) and,
     gated by the active-route check in tryRenderRoute, by normal navigation
     (AC-25, only the active view renders on first load). */
  function doRenderRoute(route) {
    if (renderedViews[route]) return;
    var file = fileForRoute(route);
    if (!file || !loaded[file]) return;
    renderedViews[route] = true;
    if (loaded[file].ok === false) {
      failSection(el(FALLBACK_CONTAINER[file]), file, loaded[file].error);
    } else {
      RENDER_FN[file](payloadData[file]);
    }
    if (pendingSub && pendingSub.route === route) {
      var id = pendingSub.id;
      pendingSub = null;
      revealAndFocus(id);
    }
  }

  function tryRenderRoute(route) {
    if (route === currentRoute) doRenderRoute(route);
  }

  function settlePayload(file) {
    load(file).then(function (json) {
      payloadData[file] = json;
      loaded[file] = { ok: true };
      if (file === 'build_status.json') renderBuild(json);
      driveCoverage();
      var route = ROUTE_FOR_FILE[file];
      if (route) tryRenderRoute(route);
    }).catch(function (error) {
      payloadData[file] = null;
      loaded[file] = { ok: false, error: error };
      driveCoverage();
      var route = ROUTE_FOR_FILE[file];
      if (route) tryRenderRoute(route);
    });
  }

  function resolveHash(hash) {
    var raw = (hash || '').replace(/^#\/?/, '');
    if (!raw) return { route: 'overview', sub: null };
    var parts = raw.split('/');
    var seg = parts[0];
    if (ROUTE_TO_ID[seg]) return { route: seg, sub: parts[1] || null };
    if (LEGACY_TO_ROUTE[seg]) return { route: LEGACY_TO_ROUTE[seg], sub: parts[1] || null, legacy: true };
    var target = document.getElementById(seg);
    if (target) {
      var viewEl = target.closest ? target.closest('.view') : null;
      if (viewEl) {
        var matchRoute = null;
        VIEWS.forEach(function (v) { if (v.id === viewEl.id) matchRoute = v.route; });
        if (matchRoute) return { route: matchRoute, sub: seg, bare: true };
      }
    }
    return { route: null, sub: raw };
  }

  function showRouteNotice(rawHash) {
    el('route-notice-slot').innerHTML = '<div class="wrap"><p class="banner banner-warning">' +
      'The address <code>#' + esc(rawHash) + '</code> does not match any view. Showing Overview instead. ' +
      'Nothing has been silently substituted or withheld.</p></div>';
  }

  function clearRouteNotice() {
    el('route-notice-slot').innerHTML = '';
  }

  function revealAndFocus(id) {
    var target = el(id);
    if (!target) return false;
    var details = target.closest ? target.closest('details') : null;
    if (details && !details.open) details.open = true;
    var detailRow = target.closest ? target.closest('tr.detail-row') : null;
    if (detailRow && detailRow.hidden) {
      detailRow.hidden = false;
      var btn = findExpandButtonFor(detailRow.id);
      if (btn) btn.setAttribute('aria-expanded', 'true');
    }
    if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
    target.focus({ preventScroll: true });
    target.scrollIntoView({ block: 'start' });
    return true;
  }

  function canonicalize(route, sub) {
    var newHash = '#/' + route + (sub ? '/' + sub : '');
    if (location.hash !== newHash) history.replaceState(null, '', newHash);
  }

  function activateView(route, subId) {
    var view = VIEW_BY_ROUTE[route];
    VIEWS.forEach(function (v) { el(v.id).hidden = v.route !== route; });
    /* The inline anti-flash boot script (index.html <head>) sets data-boot-view
       once, before this file even loads, purely to avoid a flash of every view
       stacked on first paint. Its CSS show-rule is deliberately ID-specific so
       it outranks the generic "hide every view" rule -- but that only stays
       correct if this attribute keeps tracking the active view. Without this
       line the boot view stays pinned visible (and every other .view stays
       display:none) for the rest of the page's life, no matter what `hidden`
       says: hashchange navigation would update the DOM's `hidden` attribute
       but never the one thing the CSS cascade actually keys visibility on. */
    document.documentElement.setAttribute('data-boot-view', view.id);
    document.querySelectorAll('.nav-list a[data-route]').forEach(function (link) {
      if (link.getAttribute('data-route') === route) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
    document.title = view.title + ' — Thailand Ocean Logistics Intelligence';
    currentRoute = route;
    tryRenderRoute(route);
    if (subId) {
      /* The view's payload may not have rendered yet (a sub-anchor on a
         fresh page load races the async fetch) -- doRenderRoute() retries
         this once that view's markup actually lands. */
      pendingSub = revealAndFocus(subId) ? null : { route: route, id: subId };
    } else {
      pendingSub = null;
      var heading = el(view.id + '-h');
      if (heading) heading.focus({ preventScroll: false });
    }
    el('route-status').textContent = view.label;
  }

  function applyHash() {
    var resolved = resolveHash(location.hash);
    if (!resolved.route) {
      showRouteNotice(resolved.sub || '');
      activateView('overview');
      return;
    }
    clearRouteNotice();
    activateView(resolved.route, resolved.sub);
    if (resolved.legacy || resolved.bare) canonicalize(resolved.route, resolved.sub);
  }

  document.addEventListener('click', function (e) {
    var btn = e.target && e.target.closest ? e.target.closest('.row-expand-btn') : null;
    if (btn) toggleRow(btn);
  });

  window.addEventListener('hashchange', applyHash);

  /* ---------------- print ---------------- */

  var printRestore = null;

  function fillPrintHeader() {
    var header = el('print-header');
    if (!header) return;
    var cutoff = (payloadData['build_status.json'] && payloadData['build_status.json'].data_cutoff_at) || 'unknown';
    header.innerHTML = '<p><strong>Thailand Ocean Logistics Intelligence</strong> — printed ' + esc(new Date().toISOString()) + '</p>' +
      '<p>Coverage: ' + esc(coverageState) + ' · Data cutoff: ' + esc(cutoff) + ' · ' + esc(location.href) + '</p>';
  }

  window.addEventListener('beforeprint', function () {
    fillPrintHeader();
    VIEWS.forEach(function (v) { doRenderRoute(v.route); });

    var hiddenViews = [];
    VIEWS.forEach(function (v) {
      var section = el(v.id);
      hiddenViews.push({ el: section, hidden: section.hidden });
      section.hidden = false;
    });

    var openDetails = [];
    document.querySelectorAll('details').forEach(function (d) {
      openDetails.push({ el: d, open: d.open });
      d.open = true;
    });

    var hiddenRows = [];
    document.querySelectorAll('tr.detail-row[hidden]').forEach(function (tr) { hiddenRows.push(tr); tr.hidden = false; });

    var expandedBtns = [];
    document.querySelectorAll('.row-expand-btn[aria-expanded="false"]').forEach(function (b) {
      expandedBtns.push(b);
      b.setAttribute('aria-expanded', 'true');
    });

    printRestore = { hiddenViews: hiddenViews, openDetails: openDetails, hiddenRows: hiddenRows, expandedBtns: expandedBtns };
  });

  window.addEventListener('afterprint', function () {
    if (!printRestore) return;
    printRestore.hiddenViews.forEach(function (item) { item.el.hidden = item.hidden; });
    printRestore.openDetails.forEach(function (item) { item.el.open = item.open; });
    printRestore.hiddenRows.forEach(function (tr) { tr.hidden = true; });
    printRestore.expandedBtns.forEach(function (b) { b.setAttribute('aria-expanded', 'false'); });
    printRestore = null;
  });

  /* ---------------- boot ---------------- */

  driveCoverage();
  PAYLOAD_FILES.forEach(settlePayload);
  applyHash();
})();
