/**
 * Fleet UI — Sidebar Tree Navigation
 *
 * Renders a collapsible site/zone/device tree in the sidebar.
 * - Fetches sites, zones, devices from the API
 * - Persists expand/collapse state in localStorage
 * - Supports inline search/filter
 * - Highlights current page route
 *
 * Usage:
 *   new SidebarTree({
 *     containerId: 'sidebar-tree',
 *     apiBaseUrl: '/api-proxy',
 *     currentEndpoint: request.endpoint (from Flask context)
 *   }).init();
 */

class SidebarTree {
  constructor(options = {}) {
    this.containerId = options.containerId || 'sidebar-tree';
    this.apiBaseUrl = options.apiBaseUrl || '/api-proxy';
    
    // Read context from body data attributes
    const body = document.body;
    this.currentEndpoint = body.dataset.endpoint || options.currentEndpoint || '';
    this.currentSiteId = body.dataset.currentSiteId || '';
    this.currentZoneId = body.dataset.currentZoneId || '';
    this.currentDeviceId = body.dataset.currentDeviceId || '';
    
    this.sitesCache = [];
    this.zonesCache = {}; // zonesCache[siteId] = [{id, name, ...}, ...]
    this.devicesCache = {}; // devicesCache[zoneId] = [{id, name, ...}, ...]
    this.prefetchedSiteDevices = {}; // prefetchedSiteDevices[siteId] = true

    this.expandedState = this.loadExpandedState();
    this.searchFilter = '';
  }

  async init() {
    const container = document.getElementById(this.containerId);
    if (!container) return;

    // Show skeleton while fetching sites
    container.innerHTML =
      '<div class="sidebar-loading">' +
      Array.from({length: 4}, () => '<div class="skeleton skeleton-loading-item sidebar-loading-item"></div>').join('') +
      '</div>';

    try {
      // Fetch sites once
      this.sitesCache = await this.fetchSites();

      // Expand current navigation path only (keep the rest collapsed for performance)
      if (this.currentSiteId && this.expandedState[`site-${this.currentSiteId}`] === undefined) {
        this.expandedState[`site-${this.currentSiteId}`] = true;
      }
      if (this.currentZoneId && this.expandedState[`zone-${this.currentZoneId}`] === undefined) {
        this.expandedState[`zone-${this.currentZoneId}`] = true;
      }
      this.saveExpandedState();

      // Render the tree
      await this.render();
    } catch (err) {
      console.error('[SidebarTree] Failed to initialize:', err);
      container.innerHTML = '<div class="sidebar-tree-error">Failed to load navigation</div>';
    }
  }

  async fetchSites() {
    try {
      const response = await fetch(`${this.apiBaseUrl}/sites`, {
        credentials: 'same-origin',
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (err) {
      console.error('[SidebarTree] fetchSites failed:', err);
      return [];
    }
  }

  async fetchZones(siteId) {
    if (this.zonesCache[siteId]) {
      return this.zonesCache[siteId];
    }

    try {
      const response = await fetch(`${this.apiBaseUrl}/zones?site_id=${encodeURIComponent(siteId)}`, {
        credentials: 'same-origin',
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const zones = await response.json();
      this.zonesCache[siteId] = zones;
      return zones;
    } catch (err) {
      console.error('[SidebarTree] fetchZones failed:', err);
      return [];
    }
  }

  async prefetchSiteDevices(siteId) {
    if (this.prefetchedSiteDevices[siteId]) {
      return;
    }

    try {
      const response = await fetch(`${this.apiBaseUrl}/devices?site_id=${encodeURIComponent(siteId)}`, {
        credentials: 'same-origin',
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const devices = await response.json();
      for (const device of devices) {
        const zoneId = device.zone_id;
        if (!zoneId) continue;
        if (!this.devicesCache[zoneId]) this.devicesCache[zoneId] = [];
        this.devicesCache[zoneId].push(device);
      }
      this.prefetchedSiteDevices[siteId] = true;
    } catch (err) {
      console.error('[SidebarTree] prefetchSiteDevices failed:', err);
    }
  }

  async fetchDevices(zoneId) {
    if (this.devicesCache[zoneId]) {
      return this.devicesCache[zoneId];
    }

    try {
      const response = await fetch(`${this.apiBaseUrl}/devices?zone_id=${encodeURIComponent(zoneId)}`, {
        credentials: 'same-origin',
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const devices = await response.json();
      this.devicesCache[zoneId] = devices;
      return devices;
    } catch (err) {
      console.error('[SidebarTree] fetchDevices failed:', err);
      return [];
    }
  }

  loadExpandedState() {
    try {
      const stored = localStorage.getItem('fleet-sidebar-expanded-v2');
      return stored ? JSON.parse(stored) : {};
    } catch {
      return {};
    }
  }

  saveExpandedState() {
    localStorage.setItem('fleet-sidebar-expanded-v2', JSON.stringify(this.expandedState));
  }

  isExpanded(id) {
    return this.expandedState[id] === true; // Default to collapsed for fast initial render
  }

  async toggleExpand(id) {
    this.expandedState[id] = !this.isExpanded(id);
    this.saveExpandedState();
    await this.render();
  }

  matchesFilter(text) {
    if (!this.searchFilter) return true;
    return String(text || '').toLowerCase().includes(this.searchFilter.toLowerCase());
  }

  async render() {
    const container = document.getElementById(this.containerId);
    if (!container) return;

    let html = '<div class="sidebar-tree-search"><input type="text" placeholder="Search sites..." class="tree-search-input"></div>';
    html += '<ul class="sidebar-tree-list">';

    // Overview item
    html += `<li class="tree-item tree-overview">
      <a href="/overview" class="${this.currentEndpoint === 'inventory.overview' ? 'active' : ''}">Overview</a>
    </li>`;

    // Sites
    if (this.sitesCache.length === 0) {
      html += '<li class="tree-item tree-no-sites">No sites available</li>';
    } else {
      for (const site of this.sitesCache) {
        const siteId = site.site_id || site.id;
        const siteName = site.name || site.site_id || site.id || 'Unnamed site';
        if (!this.matchesFilter(siteName)) continue;

        const expanded = this.isExpanded(`site-${siteId}`);
        const siteActive = this.currentEndpoint === 'inventory.site_view' && String(this.currentSiteId) === String(siteId);

        html += `<li class="tree-item tree-site" data-site-id="${siteId}">
          <div class="tree-node">
            <button class="tree-toggle" data-id="site-${siteId}">
              <span class="tree-chevron ${expanded ? 'open' : ''}">▶</span>
            </button>
            <a href="/sites/${siteId}" class="${siteActive ? 'active' : ''}">${this.escape(siteName)}</a>
          </div>`;

        if (expanded) {
          await this.prefetchSiteDevices(siteId);
          const zones = await this.fetchZones(siteId);
          if (zones.length > 0) {
            html += '<ul class="tree-children">';
            for (const zone of zones) {
              const zoneId = zone.zone_id || zone.id;
              const zoneName = zone.name || zone.zone_id || zone.id || 'Unnamed zone';
              if (!this.matchesFilter(zoneName)) continue;

              const zoneExpanded = this.isExpanded(`zone-${zoneId}`);
              const zoneActive = this.currentEndpoint === 'inventory.zone_view' && String(this.currentZoneId) === String(zoneId);

              html += `<li class="tree-item tree-zone" data-zone-id="${zoneId}">
                <div class="tree-node">
                  <button class="tree-toggle" data-id="zone-${zoneId}">
                    <span class="tree-chevron ${zoneExpanded ? 'open' : ''}">▶</span>
                  </button>
                  <a href="/zones/${zoneId}" class="${zoneActive ? 'active' : ''}">${this.escape(zoneName)}</a>
                </div>`;

              if (zoneExpanded) {
                const devices = await this.fetchDevices(zoneId);
                if (devices.length > 0) {
                  html += '<ul class="tree-children">';
                  for (const device of devices) {
                    const deviceId = device.device_id || device.id;
                    const deviceName = device.hostname || device.device_id || device.name || device.id || 'Unnamed device';
                    if (!this.matchesFilter(deviceName)) continue;

                    const deviceActive = this.currentEndpoint === 'inventory.device_view' && String(this.currentDeviceId) === String(deviceId);
                    html += `<li class="tree-item tree-device">
                      <a href="/devices/${deviceId}" class="${deviceActive ? 'active' : ''}">${this.escape(deviceName)}</a>
                    </li>`;
                  }
                  html += '</ul>';
                }
              }

              html += '</li>';
            }
            html += '</ul>';
          }
        }

        html += '</li>';
      }
    }

    html += '</ul>';
    container.innerHTML = html;

    const searchInput = container.querySelector('.tree-search-input');
    if (searchInput) {
      searchInput.value = this.searchFilter;
    }
    this.attachEventListeners();
  }

  attachEventListeners() {
    const container = document.getElementById(this.containerId);
    if (!container) return;

    // Toggle expand/collapse
    container.querySelectorAll('.tree-toggle').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.preventDefault();
        const id = btn.getAttribute('data-id');
        await this.toggleExpand(id);
      });
    });

    // Search filter
    const searchInput = container.querySelector('.tree-search-input');
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        this.searchFilter = e.target.value;
        this.render();
      });
    }
  }

  escape(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }
}
