const { resolve } = require("path");

module.exports = {
  root: ".",
  publicDir: false,
  build: {
    outDir: "../static/dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        lobby: resolve(__dirname, "lobby.html"),
        index: resolve(__dirname, "index.html"),
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:5000",
      "/events": {
        target: "http://127.0.0.1:5000",
        changeOrigin: true,
      },
      "/media": "http://127.0.0.1:5000",
      "/dataset": "http://127.0.0.1:5000",
    },
  },
};
