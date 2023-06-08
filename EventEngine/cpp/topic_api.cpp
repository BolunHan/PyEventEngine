#include <iostream>
#include <regex>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

extern "C" {
#include <stdlib.h>
}

class Topic : public std::unordered_map<std::string, std::string> {
public:
    class Error : public std::exception {
    public:
        explicit Error(std::string msg) : message(std::move(msg)) {}

        [[nodiscard]] const char *what() const noexcept override { return message.c_str(); }

    private:
        std::string message;
    };

    explicit Topic(std::string topic) : _value(std::move(topic)) {}

    std::string value() const { return _value; }

    virtual Topic match(const std::string &topic) const {
        if (_value == topic) {
            return Topic(topic);
        } else {
            return Topic("");
        }
    }

    std::string _value;
};

class RegularTopic : public Topic {
public:
    explicit RegularTopic(const std::string &pattern) : Topic(pattern) {}

    Topic match(const std::string &topic) const override {
        std::regex regex(_value);
        if (std::regex_match(topic, regex)) {
            Topic match(topic);
            match["pattern"] = _value;
            return match;
        } else {
            return Topic("");
        }
    }
};

class PatternTopic : public Topic {
public:
    explicit PatternTopic(const std::string &pattern) : Topic(pattern) {}

    Topic format_map(const std::unordered_map<std::string, std::string> &mapping) const {
        std::string result = _value;

        std::vector<std::string> contentVec = keys();

        for (const auto &content: contentVec) {
            auto it = mapping.find(content);
            if (it != mapping.end()) {
                std::string replacement = it->second;
                std::string searchStr = "{" + content + "}";
                size_t startPos = result.find(searchStr);
                while (startPos != std::string::npos) {
                    result.replace(startPos, searchStr.length(), replacement);
                    startPos = result.find(searchStr, startPos + replacement.length());
                }
            }
        }

        return Topic(result);
    }

    std::vector<std::string> keys() const {
        std::vector<std::string> contentVec;
        std::vector<std::string> keys;

        size_t startPos = _value.find('{');
        size_t endPos;

        while (startPos != std::string::npos) {
            endPos = _value.find('}', startPos + 1);
            if (endPos == std::string::npos)
                break;

            std::string content = _value.substr(startPos + 1, endPos - startPos - 1);
            keys.push_back(content);

            startPos = _value.find('{', endPos + 1);
        }

        return keys;
    }

    Topic match(const std::string &topic) const override {
        try {
            std::unordered_map<std::string, std::string> keyword_dict = extract_mapping(topic, _value);
            Topic match(topic);
            match.insert(keyword_dict.begin(), keyword_dict.end());
            return match;
        } catch (const Error &) {
            return Topic("");
        }
    }

    static std::unordered_map<std::string, std::string>
    extract_mapping(const std::string &target, const std::string &pattern) {
        std::unordered_map<std::string, std::string> dictionary;

        std::vector<std::string> resultParts;
        std::vector<std::string> patternParts;

        // Split the result string by '.'
        size_t startPos = 0;
        size_t dotPos = target.find('.');
        while (dotPos != std::string::npos) {
            std::string part = target.substr(startPos, dotPos - startPos);
            resultParts.push_back(part);
            startPos = dotPos + 1;
            dotPos = target.find('.', startPos);
        }
        std::string lastPart = target.substr(startPos);
        resultParts.push_back(lastPart);

        // Split the pattern string by '.'
        startPos = 0;
        dotPos = pattern.find('.');
        while (dotPos != std::string::npos) {
            std::string part = pattern.substr(startPos, dotPos - startPos);
            patternParts.push_back(part);
            startPos = dotPos + 1;
            dotPos = pattern.find('.', startPos);
        }
        lastPart = pattern.substr(startPos);
        patternParts.push_back(lastPart);

        // Check if the number of parts in result and pattern are the same
        if (resultParts.size() != patternParts.size()) {
            throw Error("Pattern not match");
        }

        // Generate the mapping dictionary
        size_t numParts = resultParts.size();
        for (size_t i = 0; i < numParts; ++i) {
            std::string resultPart = resultParts[i];
            std::string patternPart = patternParts[i];

            if (patternPart.front() == '{' && patternPart.back() == '}') {
                std::string content = patternPart.substr(1, patternPart.length() - 2);
                dictionary[content] = resultPart;
            } else {
                if (resultPart != patternPart) {
                    dictionary.clear();
                    throw Error("Pattern not match");
                }
            }
        }

        return dictionary;
    }
};

extern "C" {
Topic *create_topic(const char *topic) {
    return new Topic(topic);
}

void get_topic_value(const Topic *topic, char *buffer, size_t bufferSize) {
    std::string value = topic->value();
    strncpy(buffer, value.c_str(), bufferSize - 1);
    buffer[bufferSize - 1] = '\0';
}

const char *get_topic_value_no_buffer(const Topic *topic) {
    return topic->_value.c_str();
}

void delete_topic(Topic *topic) {
    delete topic;
}

Topic *match_topic(const Topic *topic, const char *match_topic) {
    return new Topic(topic->match(match_topic));
}

RegularTopic *create_regular_topic(const char *pattern) {
    return new RegularTopic(pattern);
}

Topic *match_regular_topic(const RegularTopic *topic, const char *match_topic) {
    return new Topic(topic->match(match_topic));
}

PatternTopic *create_pattern_topic(const char *pattern) {
    return new PatternTopic(pattern);
}

Topic *match_pattern_topic(const PatternTopic *topic, const char *match_topic) {
    return new Topic(topic->match(match_topic));
}

std::vector<std::string> *get_pattern_topic_keys(const PatternTopic *topic) {
    return new std::vector<std::string>(topic->keys());
}

void extract_mapping(const char *target, const char *pattern, std::vector<std::string> *keys,
                     std::vector<std::string> *values) {
    std::string target_str(target);
    std::string pattern_str(pattern);

    std::unordered_map<std::string, std::string> mapping = PatternTopic::extract_mapping(target_str, pattern_str);

    // Populate the keys and values vectors
    for (const auto &entry: mapping) {
        keys->push_back(entry.first);
        values->push_back(entry.second);
    }
}

const char *get_vector_value(const std::vector<std::string> *vec, int index) {
    if (index >= 0 && index < static_cast<int>(vec->size()))
        return vec->at(index).c_str();
    else
        return "";
}

int vector_size(const std::vector<std::string> *vec) {
    return vec->size();
}

void delete_vector(std::vector<std::string> *vec) {
    delete vec;
}
}

int main() {
    Topic topic("TickData.002410.SZ.Realtime");
    std::cout << topic.value() << std::endl;

    RegularTopic regularTopic("TickData.(.+).((SZ)|(SH)).((Realtime)|(History))");
    Topic match1 = regularTopic.match("TickData.1234.SZ.Realtime");
    Topic match2 = regularTopic.match("OtherData.5678.SH.History");
    std::cout << match1.value() << std::endl;
    std::cout << match2.value() << std::endl;

    PatternTopic patternTopic("TickData.{symbol}.{market}.{flag}");
    for (const std::string &i: patternTopic.keys())
        std::cout << i << std::endl;

    Topic formatted = patternTopic.format_map({{"symbol", "AAPL"},
                                               {"market", "NASDAQ"},
                                               {"flag",   "Realtime"}});
    std::cout << formatted.value() << std::endl;

    Topic match3 = patternTopic.match("TickData.ABC.NYSE.Realtime");
    Topic match4 = patternTopic.match("OtherData.XYZ.LSE.History");

    std::cout << "topic: " << match3.value() << std::endl;
    for (const auto &entry: match3) {
        std::cout << entry.first << " : " << entry.second << std::endl;
    }

    std::cout << "topic: " << match4.value() << std::endl;
    for (const auto &entry: match4) {
        std::cout << entry.first << " : " << entry.second << std::endl;
    }

    return 0;
}