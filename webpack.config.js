/* eslint-env node */
const path = require('path');
const webpack = require('webpack');

const HtmlPlugin = require('html-webpack-plugin');
const CleanPlugin = require('clean-webpack-plugin');

const src = path.resolve(__dirname, 'assets');
const dist = path.resolve(src, 'dist');

const themes = ['base', 'mint', 'indigo', 'solarized'];
let entries = {
  index: './assets/index.js',
  login: './assets/login.js'
};
let plugins = [
  new CleanPlugin([dist]),
  new HtmlPlugin({
    themes: themes,
    filename: 'login.html',
    template: 'assets/index.tpl',
    favicon: 'assets/favicon.png',
    chunks: ['login', 'theme-base']
  }),
  new HtmlPlugin({
    themes: themes,
    template: 'assets/index.tpl',
    favicon: 'assets/favicon.png',
    chunks: ['index', 'theme-base']
  })
];
for (const theme of themes) {
  let entry = 'theme-' + theme;
  entries[entry] = `./assets/${entry}.css`;
  plugins.push(
    new HtmlPlugin({
      themes: themes,
      filename: `${theme}/index.html`,
      template: 'assets/index.tpl',
      favicon: 'assets/favicon.png',
      chunks: ['index', entry]
    })
  );
}

module.exports = {
  entry: entries,
  plugins: plugins,
  output: {
    filename: '[name].js?[hash]',
    path: dist
  },
  resolve: {
    alias: {
      vue$: 'vue/dist/vue.esm.js'
    }
  },
  module: {
    rules: [
      {
        test: /\.js$/,
        exclude: /node_modules/,
        loader: 'babel-loader',
        options: {
          presets: ['babel-preset-env']
        }
      },
      {
        test: /\.(png|jpg|gif|svg)$/,
        loader: 'file-loader',
        options: {
          name: '[name].[ext]?[hash]'
        }
      },
      {
        test: /\.(html)$/,
        loader: 'html-loader'
      },
      {
        test: /\.(eot|svg|ttf|woff|woff2)$/,
        loader: 'file-loader',
        options: {
          name: '[name].[ext]?[hash]'
        }
      },
      {
        test: /\.css$/,
        use: [
          { loader: 'style-loader' },
          { loader: 'css-loader' },
          {
            loader: 'postcss-loader',
            options: {
              plugins: [
                require('postcss-import')(),
                require('postcss-cssnext')()
              ]
            }
          }
        ]
      }
    ]
  },
  devtool: '#eval-source-map'
};

if (process.env.NODE_ENV === 'production') {
  module.exports.devtool = '#source-map';
  // http://vue-loader.vuejs.org/en/workflow/production.html
  module.exports.plugins = (module.exports.plugins || []).concat([
    new webpack.DefinePlugin({
      'process.env': {
        NODE_ENV: '"production"'
      }
    }),
    new webpack.optimize.UglifyJsPlugin({
      sourceMap: true,
      compress: {
        warnings: false
      }
    }),
    new webpack.LoaderOptionsPlugin({
      minimize: true
    })
  ]);
}
