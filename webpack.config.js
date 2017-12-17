/* eslint-env node */
const path = require('path');
const webpack = require('webpack');

const CleanPlugin = require('clean-webpack-plugin');
const ExtractTextPlugin = require('extract-text-webpack-plugin');

const src = path.resolve(__dirname, 'assets');
const dist = path.resolve(src, 'dist');

module.exports = {
  entry: {
    index: './assets/index.js',
    login: './assets/login.js',
    vendor: ['vue'],
    'theme-base': './assets/theme-base.css',
    'theme-mint': './assets/theme-mint.css',
    'theme-indigo': './assets/theme-indigo.css',
    'theme-solarized': './assets/theme-solarized.css'
  },
  plugins: [
    new CleanPlugin([dist]),
    new ExtractTextPlugin({
      filename: '[name].css?[hash]'
    }),
     new webpack.optimize.CommonsChunkPlugin({
       name: 'vendor'
     })  ],
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
        use: ExtractTextPlugin.extract({
          fallback: 'style-loader',
          use: [
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
        })
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
