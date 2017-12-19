/* eslint-env node */
const path = require('path');
const webpack = require('webpack');

const CleanPlugin = require('clean-webpack-plugin');
const ExtractTextPlugin = require('extract-text-webpack-plugin');

const dist = path.resolve(__dirname, 'dist');
const prod = process.env.NODE_ENV === 'production';

module.exports = {
  entry: {
    index: __dirname + '/app.js',
    login: __dirname + '/login.js',
    vendor: ['vue'],
    'theme-base': __dirname + '/theme-base.less',
    'theme-mint': __dirname + '/theme-mint.less',
    'theme-indigo': __dirname + '/theme-indigo.less',
    'theme-solarized': __dirname + '/theme-solarized.less'
  },
  plugins: [
    new CleanPlugin([dist]),
    new ExtractTextPlugin({
      filename: '[name].css?[hash]'
    }),
    new webpack.optimize.CommonsChunkPlugin({
      name: 'vendor'
    })
  ],
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
        test: /\.less$/,
        use: ExtractTextPlugin.extract({
          fallback: 'style-loader',
          use: [
            { loader: 'css-loader', options: { sourceMap: true } },
            {
              loader: 'less-loader',
              options: {
                sourceMap: true,
                plugins: !prod
                  ? []
                  : [
                      new (require('less-plugin-autoprefix'))(),
                      new (require('less-plugin-clean-css'))({ advanced: true })
                    ]
              }
            }
          ]
        })
      }
    ]
  },
  devtool: '#source-map'
};

if (prod) {
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
    })
  ]);
}
