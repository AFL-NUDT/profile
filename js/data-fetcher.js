const CONFIG = {
    researchGateUrl: 'https://www.researchgate.net/profile/Wu-Hanshuo',
    corsProxies: [
        'https://api.allorigins.win/raw?url=',
        'https://corsproxy.io/?',
        'https://api.codetabs.com/v1/proxy?quest='
    ],
    cacheKey: 'researchgate_data_cache',
    cacheExpiry: 24 * 60 * 60 * 1000,
    fallbackData: {
        publications: 105,
        citations: 1041,
        reads: 16593,
        lastUpdated: new Date().toISOString()
    }
};

const ResearchGateDataFetcher = {
    async fetchWithProxy(url) {
        for (const proxy of CONFIG.corsProxies) {
            try {
                const response = await fetch(proxy + encodeURIComponent(url), {
                    method: 'GET',
                    headers: {
                        'Accept': 'text/html,application/xhtml+xml'
                    },
                    timeout: 10000
                });
                
                if (response.ok) {
                    return await response.text();
                }
            } catch (error) {
                console.warn(`Proxy ${proxy} failed:`, error.message);
                continue;
            }
        }
        throw new Error('All CORS proxies failed');
    },

    parseResearchGateData(html) {
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        
        const data = {
            publications: 0,
            citations: 0,
            reads: 0,
            lastUpdated: new Date().toISOString()
        };

        const publicationMatch = html.match(/Publications\s*\((\d+)\)/i) || 
                                  html.match(/(\d+)\s*Publications/i) ||
                                  html.match(/class="nova-legacy-e-text nova-legacy-e-text--size-xl[^"]*"[^>]*>(\d+)</);
        if (publicationMatch) {
            data.publications = parseInt(publicationMatch[1]);
        }

        const citationMatch = html.match(/Citations[^>]*>[\s\S]*?(\d[\d,]*)/i) ||
                              html.match(/(\d[\d,]*)\s*Citations/i) ||
                              html.match(/class="nova-legacy-e-text[^"]*nova-legacy-e-text--color-grey-700[^"]*"[^>]*>(\d[\d,]*)</);
        if (citationMatch) {
            data.citations = parseInt(citationMatch[1].replace(/,/g, ''));
        }

        const readsMatch = html.match(/Reads[^>]*>[\s\S]*?(\d[\d,]*)/i) ||
                           html.match(/(\d[\d,]*)\s*Reads/i);
        if (readsMatch) {
            data.reads = parseInt(readsMatch[1].replace(/,/g, ''));
        }

        if (data.publications === 0 && data.citations === 0 && data.reads === 0) {
            const numbers = html.match(/>\s*(\d[\d,]*)\s*</g);
            if (numbers && numbers.length >= 3) {
                const parsedNumbers = numbers
                    .slice(0, 5)
                    .map(n => parseInt(n.replace(/[><,\s]/g, '')))
                    .filter(n => !isNaN(n) && n > 0);
                
                if (parsedNumbers.length >= 3) {
                    parsedNumbers.sort((a, b) => b - a);
                    data.publications = parsedNumbers[0] || 0;
                    data.reads = parsedNumbers[1] || 0;
                    data.citations = parsedNumbers[2] || 0;
                }
            }
        }

        return data;
    },

    getCachedData() {
        try {
            const cached = localStorage.getItem(CONFIG.cacheKey);
            if (cached) {
                const data = JSON.parse(cached);
                const now = Date.now();
                const cachedTime = new Date(data.lastUpdated).getTime();
                
                if (now - cachedTime < CONFIG.cacheExpiry) {
                    return data;
                }
            }
        } catch (error) {
            console.warn('Failed to read cache:', error);
        }
        return null;
    },

    setCachedData(data) {
        try {
            localStorage.setItem(CONFIG.cacheKey, JSON.stringify(data));
        } catch (error) {
            console.warn('Failed to write cache:', error);
        }
    },

    async fetchData() {
        const cachedData = this.getCachedData();
        if (cachedData) {
            console.log('Using cached data from:', cachedData.lastUpdated);
            return { ...cachedData, fromCache: true };
        }

        try {
            console.log('Fetching fresh data from ResearchGate...');
            const html = await this.fetchWithProxy(CONFIG.researchGateUrl);
            const data = this.parseResearchGateData(html);
            
            if (data.publications > 0 || data.citations > 0 || data.reads > 0) {
                this.setCachedData(data);
                return { ...data, fromCache: false };
            }
        } catch (error) {
            console.error('Failed to fetch ResearchGate data:', error);
        }

        console.log('Using fallback data');
        return { ...CONFIG.fallbackData, fromCache: false, isFallback: true };
    },

    async refreshData() {
        localStorage.removeItem(CONFIG.cacheKey);
        return await this.fetchData();
    }
};

window.ResearchGateDataFetcher = ResearchGateDataFetcher;
window.CONFIG = CONFIG;
