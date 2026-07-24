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
    error: 'pill-critical'
  };
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

  /* Draws a sparkline in which missing periods are visible breaks. The same
     numbers are always rendered as a table alongside, so the chart is never
     the only way to read the series. */
  function sparkline(points) {
    var usable = points.filter(function (p) { return p.value !== null && p.value !== undefined; });
    if (usable.length < 2) {
      return '<p class="empty-state">Not enough usable observations to draw a chart. ' +
        'Missing periods are not plotted as zero.</p>';
    }
    var width = 640, height = 96, padX = 6, padY = 10;
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

    return '<svg class="chart" viewBox="0 0 ' + width + ' ' + height + '" preserveAspectRatio="none" ' +
      'role="img" aria-label="' + esc(label) + '">' + paths + dot + '</svg>';
  }

  function pointsTable(points, unit) {
    var rows = points.map(function (point) {
      var cell = point.value === null || point.value === undefined
        ? '<td class="missing">' + esc(words(point.value_status)) + ' — not zero</td>'
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

    return '<div class="series">' +
      '<h4>' + esc(title || series.series_id) + '</h4>' +
      '<p class="series-meta">' + (metaLines || []).map(esc).join(' · ') +
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
  }

  function renderSituation(data) {
    var banner = el('coverage-banner');
    banner.className = 'banner ' + (data.evidence_coverage === 'sufficient' ? 'banner-note' : 'banner-critical');
    banner.innerHTML = '<strong>Live coverage: ' + esc(words(data.evidence_coverage)) + '.</strong>' +
      esc(data.live_coverage_statement) + ' <br><small>' + esc(data.coverage_message) +
      ' Data cutoff ' + esc(data.data_cutoff_at) + '.</small>';

    el('situation-cards').innerHTML = [
      ['Overall direction', words(data.overall_direction), 'Transparent roll-up of the lane directions, not a composite score.'],
      ['Evidence coverage', words(data.evidence_coverage), data.coverage_message],
      ['Lanes needing attention', String(data.lanes_requiring_attention.length), 'Out of the published lane set.'],
      ['Verified operational events', String(data.active_verified_events.length), 'Reported, verified or impact-observed.'],
      ['Admitted external drivers', String(data.admitted_external_drivers.length), 'Drivers with a complete transmission chain.'],
      ['Contextual drivers', String(data.contextual_external_drivers.length), 'No transmission mechanism established; contextual only.'],
      ['Discovery leads', String(data.discovery_leads.length), 'Unconfirmed; cannot support a conclusion.']
    ].map(function (card) {
      return '<div class="card"><div class="label">' + esc(card[0]) + '</div>' +
        '<div class="value">' + esc(card[1]) + '</div>' +
        '<div class="note">' + esc(card[2]) + '</div></div>';
    }).join('');

    var attentionBody = el('attention-table').querySelector('tbody');
    attentionBody.innerHTML = data.lanes_requiring_attention.length
      ? data.lanes_requiring_attention.map(function (lane) {
          return '<tr><th scope="row">' + esc(lane.name) + '<br><small>' + esc(lane.lane_id) + '</small></th>' +
            '<td>' + pill(lane.attention_level, ATTENTION_PILL) + '</td>' +
            '<td>' + pill(lane.overall_direction, DIRECTION_PILL) + '</td>' +
            '<td>' + esc(words(lane.resolution)) + '</td></tr>';
        }).join('')
      : '<tr><td colspan="4">No lane is above routine attention.</td></tr>';

    var costBody = el('situation-cost-table').querySelector('tbody');
    costBody.innerHTML = data.cost_pressure.map(function (item) {
      return '<tr><th scope="row">' + esc(item.series_id) + '<br><small>' + esc(item.source_id || '') + '</small></th>' +
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

  function laneCard(lane) {
    var assessment = lane.assessment;
    var domains = assessment ? assessment.domain_assessments : [];
    var domainRows = domains.map(function (item) {
      return '<tr><th scope="row">' + esc(words(item.domain)) + '</th>' +
        '<td>' + pill(item.direction, DIRECTION_PILL) + '</td>' +
        '<td>' + esc(item.threshold_rule_id || 'no threshold rule (event or coverage derived)') + '</td>' +
        '<td>' + esc(item.data_period || 'none') + '</td>' +
        '<td>' + freshnessCell(item.freshness) + '</td></tr>';
    }).join('');

    return '<div class="lane-card">' +
      '<div class="badges">' +
      (assessment ? pill(assessment.attention_level, ATTENTION_PILL) : pill('insufficient_evidence', ATTENTION_PILL)) +
      (assessment ? pill(assessment.overall_direction, DIRECTION_PILL) : '') +
      '<span class="pill pill-muted">' + esc(words(lane.resolution)) + ' resolution</span>' +
      '<span class="pill pill-muted">mode: ' + esc(lane.mode) + '</span>' +
      '</div>' +
      '<h4>' + esc(lane.name) + '</h4>' +
      '<p class="meta">' + esc(lane.origin) + ' → ' + esc(lane.destination) +
      ' · ' + esc(lane.lane_id) + ' · reviewed ' + esc(lane.review_date) + ' · ' + esc(lane.status) + '</p>' +
      '<p class="meta">Chokepoints: ' + (lane.chokepoint_ids.length ? esc(lane.chokepoint_ids.join(', ')) : 'none registered') + '</p>' +
      detailsBlock('Domain assessments (9)',
        '<div class="table-wrap"><table><thead><tr><th scope="col">Domain</th><th scope="col">Direction</th>' +
        '<th scope="col">Threshold rule</th><th scope="col">Data period</th><th scope="col">Freshness</th></tr></thead>' +
        '<tbody>' + domainRows + '</tbody></table></div>') +
      detailsBlock('Selection evidence (' + lane.selection_evidence.length + ')',
        '<div class="table-wrap"><table><thead><tr><th scope="col">Criterion</th><th scope="col">Statement</th>' +
        '<th scope="col">Evidence class</th><th scope="col">Reference</th></tr></thead><tbody>' +
        lane.selection_evidence.map(function (item) {
          return '<tr><th scope="row">' + esc(words(item.criterion)) + '</th><td>' + esc(item.statement) + '</td>' +
            '<td>' + pill(item.evidence_class, {}) + '</td>' +
            '<td>' + esc(item.source_reference || 'none') + '</td></tr>';
        }).join('') + '</tbody></table></div>' +
        '<p class="prose"><strong>Data period used:</strong> ' + esc(lane.data_period_used || 'none — no dated quantitative evidence was retrieved') + '</p>') +
      detailsBlock('Known limitations (' + lane.known_limitations.length + ')', list(lane.known_limitations)) +
      '</div>';
  }

  function renderOcean(data) {
    el('port-note').textContent = data.port_interpretation_note;

    el('port-series').innerHTML = data.port_series.map(function (series) {
      return seriesBlock(series, series.series_id, [
        'Metric: ' + words(series.metric),
        'Interpretation: ' + words(series.operational_interpretation),
        'Resolution: ' + words(series.resolution),
        series.node_id || 'country level'
      ]);
    }).join('') || '<p class="empty-state">No port series available.</p>';

    el('lane-cards').innerHTML = data.lanes.map(laneCard).join('');

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

    el('notices').innerHTML = data.operational_notices.length
      ? data.operational_notices.map(function (notice) {
          return '<div class="event"><div class="badges">' +
            '<span class="pill pill-note">official notice</span>' +
            '<span class="pill pill-muted">' + esc(notice.source_class) + '</span>' +
            '<span class="pill pill-muted">licence: ' + esc(words(notice.licence_status)) + '</span></div>' +
            '<h4>' + esc(notice.source_name) + '</h4>' +
            '<p class="prose">' + esc(notice.claim) + '</p>' +
            '<p class="meta"><small>Published ' + esc(notice.publication_date || 'unknown') +
            ' · recorded ' + esc(notice.retrieved_at) +
            (notice.source_url ? ' · <a href="' + esc(notice.source_url) + '" rel="noopener noreferrer" target="_blank">source</a>' : '') +
            '</small></p>' +
            detailsBlock('Known limitations', list(notice.known_limitations)) +
            '</div>';
        }).join('')
      : '<p class="empty-state">No official operational notice is recorded. No notice channel is monitored live, ' +
        'so this is an absence of records rather than evidence that no notice was published.</p>';

    el('capacity-table').querySelector('tbody').innerHTML = data.capacity_and_service_evidence.length
      ? data.capacity_and_service_evidence.map(function (item) {
          return '<tr><th scope="row">' + esc(item.title) + '<br><small>' + esc(item.event_id) + '</small></th>' +
            '<td>' + esc(item.area) + '</td>' +
            '<td>' + pill(item.status, STATUS_PILL) + '</td>' +
            '<td>' + esc(item.severity) + '</td>' +
            '<td>' + esc(item.evidence_strength) + '</td>' +
            '<td>' + esc(item.confidence) + '</td></tr>';
        }).join('')
      : '<tr><td colspan="6">No capacity or service impact is recorded. No transit-time or ' +
        'schedule-reliability source is qualified, so this is a coverage gap.</td></tr>';
  }

  function renderTrade(data) {
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
        '<td>' + esc(item.strength) + '</td>' +
        '<td>' + esc(item.publication_date || 'unknown') + '</td>' +
        '<td>' + esc(item.retrieved_at) + '</td>' +
        '<td>' + esc(item.claim) +
        (item.source_url ? '<br><a href="' + esc(item.source_url) + '" rel="noopener noreferrer" target="_blank">source</a>' : '') +
        '</td></tr>';
    }).join('');

    return '<article class="event">' +
      '<div class="badges">' +
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
      ' · last reviewed ' + esc(event.last_reviewed_at) + '</small></p>' +
      chainList(event.transmission_chain) +
      (event.thailand_relevance_basis.length
        ? '<p class="prose"><strong>Thailand relevance basis:</strong></p>' + list(event.thailand_relevance_basis)
        : '<p class="prose"><strong>Thailand relevance:</strong> none established. The platform has found no basis to assess a Thailand effect; this is not a finding that there is none.</p>') +
      (event.closure_basis ? '<p class="prose"><strong>Closure basis:</strong> ' + esc(event.closure_basis) + '</p>' : '') +
      detailsBlock('Lane relevance (' + event.lane_relevance.length + ')',
        event.lane_relevance.length
          ? '<div class="table-wrap"><table><thead><tr><th scope="col">Lane</th><th scope="col">Relevance</th><th scope="col">Basis</th></tr></thead><tbody>' +
            event.lane_relevance.map(function (entry) {
              return '<tr><th scope="row">' + esc(entry.lane_id) + '</th><td>' + esc(entry.relevance) + '</td><td>' + esc(entry.basis) + '</td></tr>';
            }).join('') + '</tbody></table></div>'
          : '<p class="empty-state">No lane relevance established.</p>') +
      detailsBlock('Nine-area impact assessment',
        '<div class="table-wrap"><table><thead><tr><th scope="col">Area</th><th scope="col">Status</th>' +
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
        '<div class="table-wrap"><table><thead><tr><th scope="col">Source</th><th scope="col">Claim type</th>' +
        '<th scope="col">Role</th><th scope="col">Strength</th><th scope="col">Published</th>' +
        '<th scope="col">Retrieved</th><th scope="col">Claim</th></tr></thead><tbody>' + evidenceRows + '</tbody></table></div>') +
      detailsBlock('Conflicting evidence (' + event.conflicting_evidence.length + ')',
        event.conflicting_evidence.length
          ? list(event.conflicting_evidence.map(function (c) { return c.description + ' — ' + words(c.resolution_status); }))
          : '<p class="empty-state">No conflicting evidence is recorded for this event.</p>') +
      detailsBlock('Known limitations (' + event.known_limitations.length + ')', list(event.known_limitations)) +
      '</article>';
  }

  function renderEvents(data) {
    el('events-note').textContent = data.lifecycle_note;
    [
      ['events-operational', data.direct_operational_events, 'No direct operational event is recorded.'],
      ['events-admitted', data.admitted_external_drivers, 'No external driver currently has a complete transmission chain.'],
      ['events-contextual', data.contextual_external_drivers, 'No contextual external driver is recorded.'],
      ['events-leads', data.discovery_leads, 'No discovery lead is recorded.']
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

    el('approved-assessments').innerHTML = data.approved_assessments.length
      ? data.approved_assessments.map(function (item) {
          return '<div class="series"><h4>' + esc(item.package_id) + '</h4>' +
            '<p class="series-meta">Approved ' + esc(item.approved_at) + ' by ' + esc(item.reviewer_record) + '</p>' +
            '<p class="prose">' + esc(item.assessment.current_situation) + '</p></div>';
        }).join('')
      : '';

    el('deterministic-note').textContent = data.deterministic_note;
    el('outlooks').innerHTML = data.deterministic_outlooks.map(function (entry) {
      var scenarios = entry.scenarios;
      return '<div class="series">' +
        '<div class="badges">' + pill(entry.attention_level, ATTENTION_PILL) + '</div>' +
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
    ].map(function (card) {
      return '<div class="card"><div class="label">' + esc(card[0]) + '</div>' +
        '<div class="value">' + esc(card[1]) + '</div><div class="note">' + esc(card[2]) + '</div></div>';
    }).join('');

    el('capability-table').querySelector('tbody').innerHTML = data.capabilities.map(function (item) {
      return '<tr><th scope="row">' + esc(words(item.capability)) + '</th>' +
        '<td>' + pill(item.status, { sufficient: 'pill-ok', limited: 'pill-warning', insufficient: 'pill-critical' }) + '</td>' +
        '<td>' + esc(item.supporting_sources.join(', ')) + '</td>' +
        '<td>' + esc(item.gap_reason || 'none') + '</td></tr>';
    }).join('');

    el('source-list').innerHTML = data.sources.map(function (source) {
      var health = source.health || {};
      var rows = [
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

      return '<div class="series">' +
        '<div class="badges">' +
        (source.enabled ? '<span class="pill pill-ok">enabled</span>' : '<span class="pill pill-muted">disabled</span>') +
        pill(health.status || 'unknown', FRESHNESS_PILL) +
        '<span class="pill pill-note">licence: ' + esc(words(source.licence_status)) + '</span>' +
        '</div>' +
        '<h4>' + esc(source.name) + ' <small>(' + esc(source.source_id) + ')</small></h4>' +
        '<div class="table-wrap"><table><tbody>' + rows + '</tbody></table></div>' +
        detailsBlock('Enablement blockers (' + (source.blockers || []).length + ')',
          list(source.blockers, 'No blocker recorded.')) +
        detailsBlock('Known limitations (' + source.known_limitations.length + ')',
          list(source.known_limitations)) +
        '</div>';
    }).join('');

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
  }

  /* ---------------- boot ---------------- */

  var sections = [
    ['build_status.json', renderBuild, null],
    ['thailand_situation.json', renderSituation, 'situation-cards'],
    ['ocean.json', renderOcean, 'port-series'],
    ['trade.json', renderTrade, 'trade-lanes'],
    ['cost.json', renderCost, 'cost-series'],
    ['events.json', renderEvents, 'events-operational'],
    ['ai_outlook.json', renderOutlook, 'outlooks'],
    ['sources.json', renderSources, 'source-list']
  ];

  sections.forEach(function (entry) {
    load(entry[0]).then(entry[1]).catch(function (error) {
      failSection(el(entry[2]), entry[0], error);
      var banner = el('coverage-banner');
      banner.className = 'banner banner-critical';
      banner.textContent = 'One or more dashboard payloads failed to load. Treat coverage as ' +
        'insufficient until the page loads completely. (' + entry[0] + ')';
    });
  });
})();
