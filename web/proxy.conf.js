/**
 * Dev-server proxy: send the API and MCP paths to a locally running `victus serve`.
 *
 * The port is `VICTUS_API_PORT`, defaulting to the CLI's own default of 8000. Set it when
 * something else already holds that port:
 *
 *     VICTUS_API_PORT=8010 npm start
 */
const target = `http://127.0.0.1:${process.env['VICTUS_API_PORT'] || 8000}`;

module.exports = {
  '/api': { target, secure: false, changeOrigin: false },
  '/mcp': { target, secure: false, ws: true },
};
