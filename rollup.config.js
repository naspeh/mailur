import alias from "rollup-plugin-alias";
import babel from "rollup-plugin-babel";
import eslint from "rollup-plugin-eslint";
import string from "rollup-plugin-string";
import replace from "rollup-plugin-replace";

import postcss from "rollup-plugin-postcss";
import cssnext from "postcss-cssnext";

export default [
  {
    input: "assets/index.js",
    output: {
      file: "assets/dist/bundle.js",
      format: "cjs"
    },
    plugins: [
      postcss({
        extensions: [".less"],
        plugins: [cssnext()]
      }),
      eslint({
        include: "assets/*.js"
      }),
      alias({
        vue: "node_modules/vue/dist/vue.esm.js"
      }),
      babel({
        exclude: "node_modules/**"
      }),
      string({
        include: "assets/*.html"
      }),
      replace({
        "process.env.NODE_ENV": JSON.stringify("development"),
        "process.env.VUE_ENV": JSON.stringify("browser")
      })
    ]
  }
];
